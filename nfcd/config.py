"""Configuration, all from the environment."""

import os

# nfcpy device string. The bare "usb" transport does not find this board: it is
# behind a CH340 USB-serial bridge, so the tty path has to be explicit.
DEVICE = os.getenv("NFCD_DEVICE", "tty:USB0:pn532")

# Loopback by default. There is no authentication, on the assumption that only
# Spoolman on the same host talks to it.
HOST = os.getenv("NFCD_HOST", "127.0.0.1")
PORT = int(os.getenv("NFCD_PORT", "7913"))

# Ignore the same tag re-firing within this many seconds, so a tag left resting
# on the reader does not produce a stream of identical events.
RETAP_GRACE = 3.0

# Pause before retrying a reader that is missing or has failed.
RECONNECT_WAIT = 5.0

# Gap between polls when no tag is present.
POLL_IDLE = 0.3

# Transient serial errors tolerated before the reader is considered lost. This
# board produces framing errors while idle; tearing the connection down on each
# one disconnects every few seconds.
MAX_CONSECUTIVE_ERRORS = 25

# Seconds between keepalive comments on an idle event stream.
KEEPALIVE_INTERVAL = 20.0

# Events buffered per listener before the oldest are dropped. A listener this
# far behind is not going to catch up.
LISTENER_BACKLOG = 64
