# Snapmaker U1 filament handling

Optional. Nothing else in Spoolman Extended depends on it, and an installation
without a U1 should not install it.

Loading a spool on any of the U1's four channels updates that spool's
`Location` and `printer_name` in Spoolman, matching the `{Printer} @ {Gate}`
convention already used for other printers. Unloading clears it again.

## Why it is a separate process

It polls an external printer on a timer and, when the watchdog fires, sends
G-code to it. Neither belongs inside an inventory server: if Moonraker is slow
or down that must not affect the spool list, and putting printer control inside
Spoolman is a meaningful expansion of what Spoolman is.

It is also battle-tested as it stands. Rewriting it as an asyncio task inside
Spoolman would risk breaking something that works, for no visible gain.

## What the watchdog is for

SpoolLink is supposed to resolve a channel's spool the moment OpenRFID reads a
card, by looking its UID up in Spoolman's `card_uids` field. In practice that
resolve intermittently stalls forever — reproduced across channel swaps and
firmware restarts. When a channel's card does not match its lane's `spool_id`
after a grace period, this service forces it with `SET_SPOOL_ID`, the same
macro documented as the manual fallback.

## Where a tag's spool comes from

`card_uid_map.json` maps card UIDs to spool ids and is consulted first. It has
to be maintained by hand, so it goes stale the moment a tag is written by
anything that does not also edit it — which, now that Spoolman itself writes
tags, is the normal case.

So when the file has no answer, **Spoolman is asked**: its `card_uids` fields
already record every binding, and this is the same resolution the printer
performs. The result is cached for `SPOOLMAN_LOOKUP_TTL` seconds.

The practical effect is that `card_uid_map.json` is now optional. Keeping it is
harmless — anything in it still wins — but new tags no longer need adding to it.

## Install

```bash
cd /path/to/Spoolman
python3 -m venv integrations/snapmaker-u1/.venv
integrations/snapmaker-u1/.venv/bin/pip install -r integrations/snapmaker-u1/requirements.txt
sudo cp integrations/snapmaker-u1/systemd/spoollink-location-sync.service /etc/systemd/system/
sudoedit /etc/systemd/system/spoollink-location-sync.service   # replace the CHANGEME values
sudo systemctl daemon-reload
sudo systemctl enable --now spoollink-location-sync
```

An existing install elsewhere (for example under `/opt`) keeps working; this
layout is for new ones, and to keep the source with the rest of the project.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MOONRAKER_URL` | **required** | The printer's Moonraker, e.g. `http://192.168.0.202:7125` |
| `SPOOLMAN_URL` | `http://127.0.0.1:7912` | Spoolman, normally the same host |
| `PRINTER_LABEL` | `Snapmaker U1` | Name used in `Location` and `printer_name` |
| `POLL_INTERVAL_SECONDS` | `5` | Gap between polls |
| `WATCHDOG_GRACE_SECONDS` | `20` | Mismatch tolerated before forcing `SET_SPOOL_ID` |
| `CARD_UID_MAP_PATH` | next to the script | Optional UID → spool id overrides |
| `SPOOLMAN_LOOKUP_TTL` | `60` | How long a UID lookup from Spoolman stays good |

`MOONRAKER_URL` has no default on purpose. It used to default to an address
that later became wrong when the network changed subnet, and that fails
quietly: the service runs, polls nothing, and reports nothing. It now refuses
to start and says so.

## Origin

Written as a standalone project and published under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) at
[SwineFlew931/Spoolman-Snapmaker-U1-Filament-Handling-Enhancemant](https://github.com/SwineFlew931/Spoolman-Snapmaker-U1-Filament-Handling-Enhancemant),
then folded in here so there is one repository, one version and one set of
docs. CC0 is a public-domain dedication, so including it alongside MIT-licensed
code raises no conflict.
