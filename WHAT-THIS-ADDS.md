# What Spoolman Extended adds

Spoolman keeps a list of your filament — what you own, what colour it is, how
much is left. Spoolman Extended is the same program with one thing added: it
can read and write the little NFC stickers you put on your spools.

That's the whole difference. Everything else works exactly as it did.

---

## The short version

Stick a tag on a spool, tap it on a reader, and Spoolman knows which spool it
is. Your printer can know too. And when you buy a new roll, tagging it is part
of adding it rather than a separate chore afterwards.

---

## Tapping a tag finds the spool

Rest a tagged spool on the reader and Spoolman tells you what it is — no
searching, no scrolling. If the tag belongs to something already in your list,
it offers to open it.

This matters most when a spool has been sitting in a box for six months and the
label has rubbed off.

## Adding a spool ends with tagging it

Spoolman already walks you through adding a spool: who made it, what filament
it is, then the roll itself. Now that walk-through has one more step at the end
— **write the tag** — so a new roll goes from bag to shelf, labelled and
recorded, in one pass.

If you bought four rolls at once, it steps through them one at a time. You can
skip any of them and come back later. It offers to print labels at the end too,
using the label designer that was already there.

## It tells you which tags to use

Tags come in sizes, and the cheap small ones genuinely aren't big enough for
some of what gets written to them. Rather than making you work that out,
Spoolman Extended shows you a list — NTAG213, NTAG215, NTAG216 — and marks the
ones that will hold *this* spool's information, in the format you've chosen,
crossed through if they won't.

It works this out from the actual spool in front of you, not from a rule of
thumb, because the answer genuinely changes: a short filament name might fit a
small tag where a long one won't.

**If you want one answer: buy NTAG216.** They hold everything, they're cheap,
and you'll never think about it again.

## It checks its work

Three things happen quietly every time you write a tag.

**It refuses to write something that won't fit.** It asks the tag in your hand
how much room it has rather than trusting the packet it came in — which, in
testing, turned out to be worth doing.

**It reads the tag back afterwards** and compares it with what it meant to
write. If they don't match, it tells you instead of leaving you with a tag that
looks fine and isn't.

**It won't let two spools claim the same tag.** Every tag has a serial number
burned in at the factory, and cheap tags are far less unique than you'd hope —
on the ones tested here, only one byte of that number actually varies. Two of
your spools ending up with the same serial isn't a freak accident; with a few
dozen tags it's close to certain. So before linking a tag to a spool, Spoolman
checks whether anything else already claims it, and refuses if so. Without that
check, your printer could quietly load the wrong spool and bill the filament to
the wrong roll.

## Tapping a tag you've already used

Tap a tag Spoolman recognises and you get three choices: **open that spool**,
**write it again** (handy if you've corrected the colour or the weight), or
**erase the tag** so it can be reused.

Tap a blank one and it just says so.

## Retiring a spool frees its tag

When you archive a used-up spool, Spoolman Extended asks whether to release its
tag. Say yes and the tag becomes free to stick on the next roll. The tag itself
isn't wiped, so nothing is lost until you write over it.

It asks first, because once released the link is gone and re-tagging means
writing the tag again.

## Scanning barcodes without a camera

Spoolman could already scan its own QR labels with a webcam. If you have a
handheld barcode scanner — the kind that plugs in and behaves like a keyboard —
that now works too, from anywhere in the app. Point, click, and you're on the
spool.

## If you have a Snapmaker U1

There's an optional extra that keeps the printer and Spoolman in step: load a
spool into any of the four channels and Spoolman records which channel it's in;
unload it and that clears. It also works around a bug where the printer
sometimes fails to recognise a tag it has just read.

It's genuinely optional and separate. If you don't have a U1, don't install it,
and nothing will miss it.

---

## What it doesn't change

Everything else. The spool list, searching, filtering, the dashboard, the label
designer, the filament database, the way other printers talk to it — all
untouched. If you turn the NFC part off, what you have is ordinary Spoolman.

That's deliberate. This is an unofficial fork of someone else's program, and
the more it stays like the original, the easier it is to keep it up to date
with what they release next.

## What you need

- **A PN532 NFC reader.** Inexpensive, widely available, connects over USB.
- **NTAG stickers.** NTAG216 for preference; NTAG215 is usually fine.
- The reader plugs into **the machine Spoolman runs on** — for most people a
  Raspberry Pi sitting with the printers — not into the computer you're
  browsing from.

## Which tags it can and can't write

It can write the formats the 3D printing community actually uses, so a tag
written here can be read by other software and by printers that understand
them. Which format to use is a setting, and you can change it per tag; if you
have no opinion, the default is a sensible one.

Two things it can't do, and won't pretend to:

- **Bambu Lab spool tags are encrypted**, and the keys aren't public. Their
  tags can't be read or written by anything but their own printers.
- **Prusa's factory tags use a different kind of chip** that this reader
  physically cannot talk to — no software can fix that, only different
  hardware.

Neither is a limitation of this program so much as a fact about those tags.

---

## Where it came from

Spoolman is written by [Donkie](https://github.com/Donkie/Spoolman) and is
excellent. This is an unofficial fork, not affiliated with or endorsed by that
project, and bug reports about Spoolman itself belong there rather than here.
