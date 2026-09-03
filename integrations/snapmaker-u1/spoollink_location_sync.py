#!/usr/bin/env python3
"""Mirror the Snapmaker U1's per-channel spool state into Spoolman.

Polls the U1's per-channel AFC_lane Klipper objects and mirrors each channel's
active spool into Spoolman's built-in Location field and printer_name custom
field. Also runs a watchdog that force-binds a channel to the correct spool if
SpoolLink's own automatic resolve doesn't complete.

Integration point: `AFC_lane E0`..`AFC_lane E3` objects, each carrying a
per-channel `spool_id`. This is more precise than the stock `[spoolman]`
component's `notify_active_spool_set` notification, which only tracks one
global spool_id with no channel information, and more reliable than
parsing klippy.log.

Polling vs. websocket subscription: an earlier version subscribed via
Moonraker's websocket (printer.objects.subscribe / notify_status_update).
That silently stopped receiving updates after a Klipper restart --
Moonraker requires clients to re-subscribe after each notify_klippy_ready,
which the earlier version didn't do. Simple HTTP polling sidesteps that
whole class of bug: every tick is a fresh, self-contained query, so there
is no subscription state to go stale.

Watchdog: SpoolLink is supposed to auto-resolve a channel's spool the
moment OpenRFID reads a card, by looking up the card UID in Spoolman's
`card_uids` custom field. In practice (this firmware, this session) that
resolve intermittently stalls forever -- confirmed by direct log
inspection, reproduced across two separate channel-swaps and two
firmware restarts, and independent of whether the `card_uids` field
exists. If a channel's currently-read card UID (from the `filament_detect`
object) has a known mapping in card_uid_map.json and doesn't match that
channel's AFC_lane spool_id after a grace period, this script forces it
via the `SET_SPOOL_ID` Klipper macro -- the same macro documented as the
manual fallback -- bypassing SpoolLink's resolve entirely.

UID lookup: card_uid_map.json is consulted first and still wins where it has
an answer, but it has to be maintained by hand and goes stale as soon as a tag
is written by anything that doesn't also edit it. Since Spoolman now writes
tags itself, that is the normal case -- so a UID the file doesn't cover is
looked up in Spoolman's own card_uids fields instead, which is the same
resolution the printer performs. The file is therefore optional.
"""

import json
import logging
import os
import time
from urllib.parse import quote

import requests

# The printer's address has no sensible default -- it is on the network
# somewhere only the operator knows -- so it is required rather than guessed at.
# An earlier version defaulted to an address that later became wrong when the
# network moved subnet, which fails quietly: the service runs, polls nothing and
# reports nothing. Failing loudly at startup is the better trade.
MOONRAKER_URL = os.environ.get("MOONRAKER_URL", "").rstrip("/")

# Spoolman does have a sensible default: this service is meant to run on the
# Spoolman host.
SPOOLMAN_URL = os.environ.get("SPOOLMAN_URL", "http://127.0.0.1:7912").rstrip("/")

PRINTER_LABEL = os.environ.get("PRINTER_LABEL", "Snapmaker U1")
CHANNELS = [0, 1, 2, 3]
LANE_OBJECTS = [f"AFC_lane E{ch}" for ch in CHANNELS]

POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
WATCHDOG_GRACE_SECONDS = float(os.environ.get("WATCHDOG_GRACE_SECONDS", "20"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARD_UID_MAP_PATH = os.environ.get("CARD_UID_MAP_PATH", os.path.join(SCRIPT_DIR, "card_uid_map.json"))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("spoollink_location_sync")


def location_for_channel(channel: int) -> str:
    """Render the Location value for a channel, e.g. "Snapmaker U1 @ ch0"."""
    return f"{PRINTER_LABEL} @ ch{channel}"


def load_card_uid_map() -> dict:
    """Read the optional hand-maintained UID overrides."""
    try:
        with open(CARD_UID_MAP_PATH) as f:
            return {k.upper(): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        log.exception("failed to read %s", CARD_UID_MAP_PATH)
        return {}


# How long a UID lookup fetched from Spoolman stays good for. Only consulted
# when a UID is missing from card_uid_map.json, so in the steady state this
# costs nothing.
SPOOLMAN_LOOKUP_TTL = float(os.environ.get("SPOOLMAN_LOOKUP_TTL", "60"))

_spoolman_uid_cache: dict = {}
_spoolman_uid_fetched_at = 0.0


def spoolman_uid_map() -> dict:
    """Build a UID -> spool id map from Spoolman's own card_uids fields.

    card_uid_map.json has to be maintained by hand, so it goes stale the moment
    a tag is written by anything that does not also edit it -- which, now that
    Spoolman itself writes tags, is the normal case. Spoolman already knows
    every binding, so it is asked when the file does not have the answer.

    This is the same resolution the printer performs: fetch the spools and match
    on the card_uids custom field, which is a comma-separated list.
    """
    global _spoolman_uid_fetched_at
    now = time.monotonic()
    if _spoolman_uid_cache and now - _spoolman_uid_fetched_at < SPOOLMAN_LOOKUP_TTL:
        return _spoolman_uid_cache

    try:
        resp = requests.get(
            f"{SPOOLMAN_URL}/api/v1/spool",
            params={"limit": 1000, "allow_archived": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        spools = resp.json()
    except (requests.RequestException, ValueError):
        log.exception("failed to read spools from Spoolman for UID lookup")
        # Keep whatever was cached: a stale answer beats no answer, and the
        # next tick will try again.
        return _spoolman_uid_cache

    built = {}
    for spool in spools:
        raw = (spool.get("extra") or {}).get("card_uids")
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = raw
        if not isinstance(value, str):
            continue
        for part in value.split(","):
            uid = part.strip().upper()
            if uid:
                built[uid] = spool["id"]

    _spoolman_uid_cache.clear()
    _spoolman_uid_cache.update(built)
    _spoolman_uid_fetched_at = now
    return _spoolman_uid_cache


def query_moonraker_objects() -> dict:
    """Fetch the four lane objects and the card reader state in one request."""
    query = "&".join(quote(name) for name in [*LANE_OBJECTS, "filament_detect"])
    resp = requests.get(f"{MOONRAKER_URL}/printer/objects/query?{query}", timeout=10)
    resp.raise_for_status()
    return resp.json()["result"]["status"]


def card_uid_hex(raw_uid: object) -> str:
    """Render a card UID the way Spoolman stores it: uppercase hex, no separators."""
    if not raw_uid or not any(raw_uid):
        return ""
    return "".join(f"{b:02X}" for b in raw_uid)


def force_spool_id(channel: int, spool_id: int) -> None:
    """Bind a channel to a spool directly, bypassing SpoolLink's own resolve."""
    script = f"SET_SPOOL_ID LANE=E{channel} SPOOL_ID={spool_id}"
    try:
        resp = requests.post(
            f"{MOONRAKER_URL}/printer/gcode/script",
            json={"script": script},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("watchdog: forced ch%s -> spool #%s (%s)", channel, spool_id, script)
    except requests.RequestException:
        log.exception("watchdog: failed to run %r", script)


def patch_spool(spool_id: int, location: str | None) -> None:
    """PATCH a spool's Location and printer_name in Spoolman.

    Custom fields are double-JSON-encoded: the API expects the
    field's JSON-encoded value as a string, e.g. a text field holding
    "Snapmaker U1" is sent as '"Snapmaker U1"'.
    """
    payload = {
        "location": location or "",
        "extra": {"printer_name": json.dumps(PRINTER_LABEL if location else "")},
    }
    url = f"{SPOOLMAN_URL}/api/v1/spool/{spool_id}"
    try:
        resp = requests.patch(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("spool #%s -> location=%r", spool_id, payload["location"])
    except requests.RequestException:
        log.exception("failed to PATCH spool #%s", spool_id)


def handle_lane_update(channel: int, old_spool_id: int, new_spool_id: int) -> None:
    """Move a channel's location from the spool leaving it to the one arriving."""
    if old_spool_id == new_spool_id:
        return
    if old_spool_id and old_spool_id != new_spool_id:
        patch_spool(old_spool_id, None)
    if new_spool_id:
        patch_spool(new_spool_id, location_for_channel(channel))


def run() -> None:
    """Poll the printer forever, mirroring lane state into Spoolman."""
    last_spool_id = {}
    mismatch_since = {}
    last_forced = {}
    last_warned_unknown_uid = {}
    initialized = False

    while True:
        try:
            status = query_moonraker_objects()
        except requests.RequestException as exc:
            log.warning("Moonraker query failed (%s), retrying in %ss", exc, POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        card_uid_map = load_card_uid_map()
        filament_info = status.get("filament_detect", {}).get("info", [])
        now = time.monotonic()

        for channel in CHANNELS:
            lane = status.get(f"AFC_lane E{channel}", {})
            current_spool_id = lane.get("spool_id") or 0

            # Deliberately not skipped on the first pass: if this service
            # was down or stalled (see module docstring) while a channel's
            # spool changed, Spoolman would otherwise stay stale forever.
            # Re-asserting the current location on every startup is a cheap,
            # idempotent PATCH -- self-healing beats avoiding a redundant call.
            if current_spool_id != last_spool_id.get(channel, 0):
                handle_lane_update(channel, last_spool_id.get(channel, 0), current_spool_id)
                last_spool_id[channel] = current_spool_id

            # Watchdog: does the physically-loaded card agree with spool_id?
            uid = card_uid_hex(filament_info[channel]["CARD_UID"]) if channel < len(filament_info) else ""
            if not uid:
                mismatch_since.pop(channel, None)
                last_forced.pop(channel, None)
                continue

            # The file wins when it has an answer, so nothing that worked before
            # behaves differently; Spoolman is consulted only for what it does
            # not cover.
            expected_spool_id = card_uid_map.get(uid)
            if expected_spool_id is None:
                expected_spool_id = spoolman_uid_map().get(uid)
            if expected_spool_id is None:
                if last_warned_unknown_uid.get(channel) != uid:
                    log.warning(
                        "ch%s: card UID %s is not in %s and no spool in Spoolman "
                        "claims it -- bind it once (write the tag from Spoolman, "
                        "or use the Filament Manager UI or SET_SPOOL_ID)",
                        channel,
                        uid,
                        CARD_UID_MAP_PATH,
                    )
                    last_warned_unknown_uid[channel] = uid
                continue

            if expected_spool_id == current_spool_id:
                mismatch_since.pop(channel, None)
                last_forced.pop(channel, None)
                continue

            first_seen = mismatch_since.setdefault(channel, now)
            if now - first_seen >= WATCHDOG_GRACE_SECONDS and last_forced.get(channel) != expected_spool_id:
                force_spool_id(channel, expected_spool_id)
                last_forced[channel] = expected_spool_id

        if not initialized:
            log.info("initial lane state: %s", last_spool_id)
            initialized = True

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> int:
    """Check the configuration, then run.

    Returns:
        int: Process exit status.

    """
    if not MOONRAKER_URL:
        log.error(
            "MOONRAKER_URL is not set. Point it at the printer's Moonraker, "
            "e.g. MOONRAKER_URL=http://192.168.0.202:7125"
        )
        return 1
    log.info("polling %s, writing to %s", MOONRAKER_URL, SPOOLMAN_URL)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
