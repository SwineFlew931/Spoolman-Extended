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

It is also **deployed** separately, outside the Spoolman directory. Spoolman is
now a stock checkout that gets replaced on upgrade, and this service needs none
of its code — only its published REST API. Anything living inside that checkout
is in the blast radius of every upgrade for no benefit. The NFC reader service
is arranged the same way.

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

Spoolman 0.27 keeps tag bindings in a `tag` table, exposed as each spool's
`tags`. **That is the source of truth here.** Resolution order:

1. `card_uid_map.json`, if it has an answer. Hand-maintained, optional, and it
   still wins so that anything that worked before behaves the same.
2. The tag table.
3. `card_uids`, for a UID no tag mentions — a binding made by hand or by the
   printer that has not been reconciled yet.

## Why card_uids is still maintained

The U1's firmware reads `card_uids`, not the tag table. Spoolman 0.27 writes
only the tag table, so **without a mirror the printer's own instant resolve is
blind to every tag written since the upgrade**, leaving this service's watchdog
as the only thing that ever binds a channel — which means waiting out
`WATCHDOG_GRACE_SECONDS` on every single load.

So `reconcile_card_uids` makes `card_uids` match `tags`. It appends freely.
Removals are deliberately conservative, because that field is also written by
hand and by other tools, and dropping someone else's value is worse than keeping
a spare one. Only a UID the tag table actively contradicts is pruned:

- **the tag table gives it to a different spool** — this copy is a leftover that
  would resolve a channel to the wrong filament;
- **the spool is archived and has no tag for it** — which is exactly what
  archive-frees-tag means; without this the printer keeps binding an archived
  spool.

A UID no tag claims, on a live spool, is left alone and logged once.

## Install

```sh
mkdir -p ~/spoollink-sync && cd ~/spoollink-sync
# copy spoollink_location_sync.py and requirements.txt here
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then the unit in `systemd/`: replace the `CHANGEME` values, copy it to
`/etc/systemd/system/`, `daemon-reload`, `enable --now`.

An existing install elsewhere (for example under `/opt`, or inside an older
Spoolman tree) keeps working; this layout is for new ones.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MOONRAKER_URL` | **required** | The printer's Moonraker, e.g. `http://192.168.0.202:7125` |
| `SPOOLMAN_URL` | `http://127.0.0.1:7913` | Spoolman itself, behind the proxy on the same host |
| `PRINTER_LABEL` | `Snapmaker U1` | Name used in `Location` and `printer_name` |
| `POLL_INTERVAL_SECONDS` | `5` | Gap between polls |
| `WATCHDOG_GRACE_SECONDS` | `20` | Mismatch tolerated before forcing `SET_SPOOL_ID` |
| `CARD_UID_MAP_PATH` | next to the script | Optional UID → spool id overrides |
| `SPOOLMAN_LOOKUP_TTL` | `60` | How long a fetch of Spoolman's spools stays good |
| `SPOOLLINK_DRY_RUN` | unset | Log every write instead of making it |

`MOONRAKER_URL` has no default on purpose. It used to default to an address
that later became wrong when the network changed subnet, and that fails
quietly: the service runs, polls nothing, and reports nothing. It now refuses
to start and says so.

`SPOOLLINK_DRY_RUN` is worth one run on a live inventory: the reconcile is the
only part that writes to spools without the printer having asked it to.

## Tests

```sh
python3 -m pytest test_spoollink_location_sync.py
```

They cover the reconcile's pruning rules, which is where a bug costs real data.

## Origin

Written as a standalone project and published under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) at
[SwineFlew931/Spoolman-Snapmaker-U1-Filament-Handling-Enhancemant](https://github.com/SwineFlew931/Spoolman-Snapmaker-U1-Filament-Handling-Enhancemant),
then folded in here so there is one repository, one version and one set of
docs. CC0 is a public-domain dedication, so including it alongside MIT-licensed
code raises no conflict.
