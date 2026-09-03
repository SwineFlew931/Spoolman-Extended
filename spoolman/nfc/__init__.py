"""NFC tag reading and writing.

The reader hardware is driven by a separate process (``nfcd``) rather than from
inside Spoolman. See ``nfcd/README.md`` for why. This package holds everything
on the Spoolman side of that boundary: the client that talks to the daemon, and
the logic that turns spools into tag payloads and tag UIDs back into spools.
"""
