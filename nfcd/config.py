"""Configuration, all from the environment."""

import os

# How to find the reader. These are tried in order by nfcd.device.resolve(),
# which runs before every connection attempt, so a reader that moves ports or
# comes back under a different kernel index is picked up on the next retry.
#
# Note the default is now empty. It used to be "tty:USB0:pn532", and that was a
# bug: ttyUSB0 is not a property of the reader, just whichever minor happened to
# be free when the driver probed. Moving the reader to another port made it
# enumerate as ttyUSB1, and no amount of retrying could ever find USB0 again.
#
# 1. An explicit nfcpy device string. The escape hatch -- the only way to reach a
#    reader that is not a USB bridge, and what older installs already set. Note
#    that nfcpy cannot parse a path here; use NFCD_DEVICE_PATH for that.
DEVICE = os.getenv("NFCD_DEVICE", "")

# 2. A path to the device node, or to any symlink pointing at it. A
#    /dev/serial/by-path/... link or the /dev/nfc-reader name created by
#    nfcd/udev/99-spoolman-nfc.rules both survive a reboot; the kernel index
#    does not. Resolved to a real node on each attempt.
DEVICE_PATH = os.getenv("NFCD_DEVICE_PATH", "")

# 3. The physical USB port, as pyserial spells it (e.g. "1-1.1"). Use this when
#    two identical bridges are on the bus, since a CH340 carries no serial
#    number to tell them apart. Unlike the options above, this deliberately
#    means "whatever is in this socket" -- which is what a reader mounted in a
#    specific spool holder wants.
USB_LOCATION = os.getenv("NFCD_USB_LOCATION", "")

# 4. Vendor:product IDs to search for, the default. 1a86:7523 is the CH340
#    bridge this reader sits behind. Correct whenever there is one reader: it
#    follows the hardware to any port with no configuration at all. Several
#    matches is an error rather than a guess -- opening the wrong bridge can
#    drive an unrelated device -- and NFCD_USB_LOCATION breaks the tie.
USB_IDS = {
    tuple(int(part, 16) for part in pair.split(":", 1))
    for pair in os.getenv("NFCD_USB_IDS", "1a86:7523").split(",")
    if pair.strip()
}

# nfcpy driver name appended to whichever node is resolved. The bare "usb"
# transport does not find this board, because it is behind a serial bridge
# rather than being a USB NFC device in its own right.
DRIVER = os.getenv("NFCD_DRIVER", "pn532")

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
