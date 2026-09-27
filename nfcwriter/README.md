# nfcwriter

Writes filament data to NFC tags for a **stock, unmodified Spoolman**.

Spoolman 0.27 reads tags and links them to spools. It has no notion of putting
data *on* a tag. This service adds that without forking Spoolman's backend: it
owns the reader, renders a spool into a tag format, writes it, and reports the
UID it wrote to. Linking that UID stays Spoolman's job.

```
browser ──► Spoolman         (spools, tags, linking — untouched upstream)
       └──► nfcwriter :7914  (reader, formats, writing)
                 └──► Spoolman REST API (read a spool; forward ambient taps)
```

It reads Spoolman over the public REST API and **never touches its database**, so
it cannot corrupt an install and Spoolman can be upgraded on its own schedule.

## What it needs from the client

One module, `client_v2/src/lib/api/nfcWriter.ts`, plus a write dialog and a store.
Three new files and two touched, none of them Python — see `../WHAT-THIS-ADDS.md`.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout "$USER"        # log out and back in
sudo cp udev/99-spoolman-nfc.rules /etc/udev/rules.d/   # optional, see below
sudo cp systemd/nfcwriter.service /etc/systemd/system/  # edit the paths first
sudo systemctl daemon-reload && sudo systemctl enable --now nfcwriter
```

Check it: `curl localhost:7914/status`

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NFCW_SPOOLMAN_URL` | `http://127.0.0.1:7912` | Where to read spools from |
| `NFCW_ALLOWED_ORIGINS` | `*` | CORS origins. Narrow this on an untrusted network |
| `NFCW_PORT` | `7914` | Port to listen on |
| `NFCW_HOST` | `0.0.0.0` | Interface. Not loopback: the browser calls this directly |
| `NFCW_FORWARD_SCANS` | `true` | Forward ambient taps to Spoolman's `/tag/scan` |
| `NFCW_READER_ID` | `nfcwriter` | Name this reader reports as |
| `NFCW_USB_IDS` | `1a86:7523` | USB vendor:product to find the reader by |
| `NFCW_DEVICE_PATH` | *(unset)* | A device node or symlink to use instead |
| `NFCW_USB_LOCATION` | *(unset)* | A physical USB port (e.g. `1-1.1`) to use instead |
| `NFCW_DEVICE` | *(unset)* | An explicit nfcpy device string, overriding the above |

CORS is not optional: this is a different origin from Spoolman, so Spoolman's
origin must be allowed or the browser refuses every request before sending it.

### Finding the reader

Out of the box nothing needs setting — the reader is found by USB ID and followed
to whatever port it is in. It is deliberately *not* configured as `ttyUSB0`; see
`device.py` for the failure that taught us why, which was unrecoverable and in
which two faults concealed each other.

For more than one reader, a CH340 carries no USB serial number, so the only thing
telling two apart is which socket each is in: use `NFCW_USB_LOCATION`, or install
`udev/99-spoolman-nfc.rules` for stable `/dev/nfc-*` names.

## API

| Endpoint | Purpose |
|---|---|
| `GET /status` | Reader state: connected, device, error, transient error count |
| `GET /formats` | The tag formats on offer, for the write dialog's dropdown |
| `POST /preview` | `{spool_id, format}` → payload size, notes, which chips fit |
| `POST /write` | `{spool_id, format, timeout}` → arms the reader, waits, reports the UID |
| `POST /erase` | `{timeout}` → blanks the next tag presented |
| `POST /cancel` | Disarm the reader |
| `GET /events` | SSE stream of `reader_status`, `tag`, `armed`, `write_ok`, `write_failed` |

`/write` and `/erase` hold the request open until the tag is dealt with, so the
request *is* the operation: closing it cancels and disarms the reader.

There is no "tag removed" event — the reader polls and reports what it finds, and
cannot tell a tag still resting on it from one presented again.

### Linking is not done here

`/write` reports a UID; it does not link it. The client links it through
Spoolman's `POST /spool/{id}/tag`, the same call the by-hand flow uses.

Writing happens first on purpose: a tag linked but not written is a lie the user
cannot see, whereas a tag written but not linked is visible in the tag list and
can be linked from there.

## Formats

| Key | Writes | Notes |
|---|---|---|
| `opentag3d` | binary memory map | Default. The Snapmaker U1 does **not** decode it — see below |
| `openspool` | JSON | Decoded by the U1 and by most community tooling |
| `nfc2klipper` | NDEF text | `SPOOL:<id>\nFILAMENT:<id>`. Tiny, fits an NTAG210 |
| `uid_only` | nothing | Links a blank tag by its UID alone |

Measured on a Snapmaker U1 running Paxx12 firmware: an OpenTag3D tag reports
`MAIN_TYPE NONE` and zero temperatures, while an OpenSpool tag reports real
values. The U1 still shows the right filament either way, because the UID link
resolves through Spoolman — but only OpenSpool works without Spoolman reachable.

## Tests

```bash
python -m pytest tests/nfcwriter/ -q
```

Ported wholesale from the integrated version, minus the binding tests: linking is
Spoolman's now, so the 266 lines that did it here are gone rather than moved.
