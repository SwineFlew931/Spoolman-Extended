# nfcd — the NFC reader daemon

A small process that owns the PN532 reader and nothing else. Spoolman talks to
it over loopback; the browser never does.

## Why it is a separate process

nfcpy blocks while polling, so the reader needs a thread of its own wherever it
lives. That much a thread inside Spoolman would handle. The reason it is a
separate *process* is failure, not concurrency:

- This reader can end up in a state that only a restart clears. A daemon under
  `Restart=always` recovers by itself; a thread stuck in a serial read cannot be
  killed, so clearing it would mean restarting the server your printers talk to.
- `nfcpy` and `pyserial` stay out of Spoolman's dependencies. An installation
  with no reader is byte-for-byte upstream Spoolman plus some unused endpoints.

## What it does and does not know

It finds tags, reads their NDEF records, writes records to them, and reports
what happened. It has no idea what a spool is, and no idea what any tag format
means: payloads arrive already encoded and come back as raw bytes. Every
decision about *content* is made in Spoolman.

The one piece of judgement it does contribute is capacity. `tag.ndef.capacity`
is read from the tag in hand and a write that will not fit is refused before it
is attempted, because a tag's advertised capacity is not always right — the
NTAG216 clones in use here claim 872 bytes in their capability container and
actually hold 888.

## Install

```bash
cd /path/to/Spoolman
python3 -m venv nfcd/.venv
nfcd/.venv/bin/pip install -r nfcd/requirements.txt
sudo cp nfcd/systemd/spoolman-nfc.service /etc/systemd/system/
sudoedit /etc/systemd/system/spoolman-nfc.service   # replace the CHANGEME values
sudo systemctl daemon-reload
sudo systemctl enable --now spoolman-nfc
```

The user it runs as must be in the `dialout` group.

Then tell Spoolman it may use it, in Spoolman's own `.env`:

```
SPOOLMAN_NFC_ENABLED=TRUE
SPOOLMAN_NFCD_URL=http://127.0.0.1:7913
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NFCD_USB_IDS` | `1a86:7523` | USB vendor:product to search for. Comma-separated |
| `NFCD_DEVICE_PATH` | *(unset)* | A device node, or a symlink to one, to use instead |
| `NFCD_USB_LOCATION` | *(unset)* | A physical USB port (e.g. `1-1.1`) to use instead |
| `NFCD_DEVICE` | *(unset)* | An explicit nfcpy device string, overriding all of the above |
| `NFCD_DRIVER` | `pn532` | nfcpy driver appended to the resolved node |
| `NFCD_HOST` | `127.0.0.1` | Interface to listen on |
| `NFCD_PORT` | `7913` | Port to listen on |

Out of the box nothing needs setting: the reader is found by USB ID and followed
to whatever port it is in.

### Why not just name the port

`NFCD_DEVICE` used to default to `tty:USB0:pn532`, and that was a bug. Moving
the reader from one USB socket to another broke it in a way that could not
recover, and the two halves of the failure concealed each other:

1. When the device vanished, nfcpy's `close()` raised while talking to the
   absent chipset, before it reached the serial handle — so the file descriptor
   stayed open.
2. An open descriptor keeps its kernel minor allocated, so `ttyUSB0` could not
   be reissued. The reader came back as `ttyUSB1`, and then as `ttyUSB1` from
   *every* port thereafter.
3. Configuration still said `USB0`, which could now never reappear. The daemon
   retried forever against a name that no longer existed.

`ttyUSBn` is not a property of the reader; it is whichever minor happened to be
free when the driver probed. So the device is resolved before *every* connection
attempt, and the descriptor is released deterministically
(`nfcd/device.py:release`) rather than best-effort. A removal is also
distinguished from this board's ordinary idle framing noise
(`nfcd/device.py:is_gone`), so a vanished node is let go of at once instead of
being polled for the 25 errors a real glitch is allowed.

The nfcpy `usb` transport is still not usable here: this board sits behind a
CH340 USB-serial bridge rather than being a USB NFC device in its own right.

### More than one reader

A CH340 carries no USB serial number, so two of them are indistinguishable by
identity — only by which socket they are in. `nfcd` refuses to guess: if several
bridges match `NFCD_USB_IDS` it reports them all and exits that attempt. Use
`NFCD_USB_LOCATION`, or install `udev/99-spoolman-nfc.rules` for stable
`/dev/nfc-*` names and point `NFCD_DEVICE_PATH` at one.

### A wedged board

Distinct from anything above, and not software-recoverable: the PN532 can end up
in a state where it answers nothing at all, not even a raw
`GetFirmwareVersion` frame. A USB reset does not clear it and neither does the
datasheet wake-up preamble, because the chip has not lost power. Only cutting
Vbus does, which means physically unplugging it. `_suppress_power_down` in
`reader.py` exists to stop nfcpy provoking this on close.

## API

| Endpoint | Purpose |
|---|---|
| `GET /status` | Reader state: device, connected, error, transient error count, what is armed |
| `GET /events` | SSE stream of `reader_status`, `tag`, `armed`, `write_ok`, `write_failed`, `cancelled`, `error` |

There is no "tag removed" event: the reader polls and reports what it finds,
and cannot distinguish a tag still resting on it from one presented again. A
client that raises something on a tap therefore has to remember what it has
already dealt with.
| `POST /write` | Arm a write for the next tag: `{records: [{type, name, data_b64}], request_id}` |
| `POST /erase` | Arm a blanking of the next tag: `{request_id}` |
| `POST /cancel` | Disarm |

Writes are asynchronous by nature — the tag has not been presented yet — so
`/write` returns as soon as it is armed and the outcome arrives on the event
stream, tagged with the same `request_id`.

Every write is read back and compared before it is reported as successful.

## Expected noise

`transient_errors` climbing is normal. This board produces framing errors
("frame length value mismatch", "frame data checksum error", `[Errno 5]`) while
idle; they are serial desync, not a failing reader, and are tolerated in runs of
up to 25 before the connection is rebuilt. A reader that is genuinely gone shows
up as `connected: false` with an error, and is retried every 5 seconds.
