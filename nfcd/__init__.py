"""nfcd — the NFC reader daemon for Spoolman Extended.

A deliberately small process that owns the PN532 and nothing else. It knows how
to find a tag, read its NDEF records, write records to it and report what
happened. It knows nothing about spools, filaments or tag formats: payloads
arrive already encoded and are handed back as raw bytes.

It exists as a separate process because this reader can wedge in a way that
needs a restart (see README.md), and restarting a 200-line daemon is very
different from restarting the server the printers talk to.
"""
