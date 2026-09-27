"""Writes filament data to NFC tags for Spoolman.

A separate service on purpose. Spoolman reads tags and links them to spools; it
has no notion of writing one, and adding that would mean forking its backend.
Keeping the writing here means a stock Spoolman can be upgraded on its own
schedule, and the only thing that knows this service exists is one module in the
client (`lib/api/nfcWriter.ts`).

The division of labour is the whole design:

  * This service owns the reader, renders a spool into a tag format, writes it,
    and reports the UID it wrote to.
  * Spoolman links that UID, through the same API the by-hand flow uses.

So it reads from Spoolman's REST API and never touches its database. It cannot
corrupt an install, which is what makes running it alongside one reasonable.
"""
