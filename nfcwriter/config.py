"""Configuration, all from the environment."""

import os

# --- the reader ------------------------------------------------------------
# See device.py for why the kernel index is not among these. Out of the box
# nothing needs setting: the reader is found by USB ID and followed to whatever
# port it is in.

DEVICE = os.getenv("NFCW_DEVICE", "")
DEVICE_PATH = os.getenv("NFCW_DEVICE_PATH", "")
USB_LOCATION = os.getenv("NFCW_USB_LOCATION", "")
USB_IDS = {
    tuple(int(part, 16) for part in pair.split(":", 1))
    for pair in os.getenv("NFCW_USB_IDS", "1a86:7523").split(",")
    if pair.strip()
}
DRIVER = os.getenv("NFCW_DRIVER", "pn532")

# --- the service -----------------------------------------------------------
# Bound to all interfaces, unlike the integrated daemon's loopback default,
# because the browser now talks to this service directly: it is a different
# origin from Spoolman and localhost would put it out of reach.
HOST = os.getenv("NFCW_HOST", "0.0.0.0")
PORT = int(os.getenv("NFCW_PORT", "7914"))

# Origins allowed to call this service. Spoolman's own origin has to be listed
# or the browser refuses every request, so this is effectively required. "*" is
# accepted for a trusted LAN and is the documented quick start; it is not the
# default, because a default that works everywhere is also one nobody revisits.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("NFCW_ALLOWED_ORIGINS", "*").split(",") if o.strip()]

# --- Spoolman --------------------------------------------------------------
# Read-only, and used for exactly two things: reading a spool so a format can be
# built from it, and forwarding ambient taps so Spoolman's own scan handling
# works. This service never writes to the database.
SPOOLMAN_URL = os.getenv("NFCW_SPOOLMAN_URL", "http://127.0.0.1:7912").rstrip("/")

# Whether to forward tags tapped when no write is armed to Spoolman's
# POST /api/v1/tag/scan. That is what makes a paired browser jump to the spool,
# so this service behaves like any other reader when it is not writing.
FORWARD_SCANS = os.getenv("NFCW_FORWARD_SCANS", "true").lower() not in ("0", "false", "no")

# Name this reader reports itself as when forwarding scans, so Spoolman's
# scanner settings can tell several readers apart.
READER_ID = os.getenv("NFCW_READER_ID", "nfcwriter")

# How long before the same tag counts as a new tap rather than one that was
# never lifted off the reader. The reader cannot tell the two apart, and a
# spool parked on it would otherwise drag a paired browser back to that spool
# every few seconds. A different tag is always news and ignores this.
RESCAN_INTERVAL = float(os.getenv("NFCW_RESCAN_INTERVAL", "30"))

# --- polling behaviour -----------------------------------------------------
# Unchanged from the integrated daemon; each value is explained where it is used.
RETAP_GRACE = 3.0
RECONNECT_WAIT = 5.0
POLL_IDLE = 0.3
MAX_CONSECUTIVE_ERRORS = 25
KEEPALIVE_INTERVAL = 20.0
LISTENER_BACKLOG = 64
