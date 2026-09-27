"""Insert the nfc.* keys into en/common.json in sorted position.

A script rather than a one-off edit because `npm run build` strips every locale
file in place (upstream's strip-empty-locales prebuild), and restoring them with
git checkout takes these additions with it. Run after building, not before.
"""
import pathlib
import sys

NEW = {
    "nfc.archiveFreeFailed": "Could not free the tag. The spool has not been archived.",
    "nfc.archiveFreeing": "Freeing the tag...",
    "nfc.archiveFreesTag": "Archiving this spool releases its tag, so it can be used on another roll. The tag is not erased.",
    "nfc.archiveFreesTags": "Archiving this spool releases its {{count}} tags, so they can be used on other rolls. The tags are not erased.",
    "nfc.armed": "Ready — present the tag to the reader",
    "nfc.armedHint": "Hold the tag still until it reports back.",
    "nfc.bound": "Tag linked to this spool.",
    "nfc.cancel": "Cancel",
    "nfc.chipFits": "fits, {{headroom}} bytes spare",
    "nfc.chipTooSmall": "too small by {{over}} bytes",
    "nfc.erase.action": "Erase tag",
    "nfc.erase.body": "This blanks the tag. The spool itself is not changed.",
    "nfc.erase.confirm": "Erase it",
    "nfc.erase.done": "Tag erased.",
    "nfc.erase.title": "Erase this tag?",
    "nfc.erase.unbindBody": "It will also stop identifying {{name}}.",
    "nfc.erase.unbound": "Tag erased and unlinked.",
    "nfc.erase.unlinkFailed": "Tag erased, but unlinking {{uid}} failed. Remove it from the tag list.",
    "nfc.format.label": "Tag format",
    "nfc.goToSpool": "Go to it",
    "nfc.linkConflict": "Written, but {{uid}} is already linked to something else. Link it from the tag list to move it.",
    "nfc.linkFailed": "Written, but linking {{uid}} failed. Add it from the tag list to retry.",
    "nfc.linking": "Linking the tag...",
    "nfc.notesTitle": "Notes",
    "nfc.nothingWritten": "This format writes nothing to the tag; it links the tag's UID only.",
    "nfc.overwrite": "Write it again",
    "nfc.payloadSize": "Payload: {{size}} bytes",
    "nfc.reader.offline": "The reader is not responding.",
    "nfc.recommendedHint": "Capacity is the usable NDEF message size, which is smaller than the chip's advertised total.",
    "nfc.recommendedTags": "Recommended tags",
    "nfc.retry": "Try again",
    "nfc.tagFound.blank": "This tag is blank.",
    "nfc.tagFound.checking": "Checking what this tag identifies...",
    "nfc.tagFound.known": "This tag identifies {{name}}.",
    "nfc.tagFound.title": "Tag detected",
    "nfc.tagFound.unknownData": "This tag holds {{format}} data, but nothing here claims it.",
    "nfc.uid": "UID",
    "nfc.writeAction": "Write tag",
    "nfc.writerUnreachable": "No tag writer at {{url}}.",
    "nfc.written": "Written — {{bytes}} bytes, read back and verified.",
}

p = pathlib.Path("client_v2/locales/en/common.json")
lines = p.read_text().split("\n")


def key_of(line: str) -> str | None:
    s = line.strip()
    return s.split('"')[1] if s.startswith('"') else None


# Rewrite the value of any key we already own, so changing the wording here is
# enough -- the file is regenerated after every build and a stale value would
# otherwise survive forever.
updated = 0
for i, line in enumerate(lines):
    k = key_of(line)
    if k in NEW:
        indent = line[: len(line) - len(line.lstrip())]
        lines[i] = '%s"%s": "%s",' % (indent, k, NEW[k].replace('"', '\\"'))
        updated += 1

existing = {key_of(line) for line in lines}
added = 0
for k in sorted(NEW):
    if k in existing:
        continue
    entry = '    "%s": "%s",' % (k, NEW[k].replace('"', '\\"'))
    for i, line in enumerate(lines):
        ek = key_of(line)
        if ek is not None and ek > k:
            lines.insert(i, entry)
            added += 1
            break
    else:
        sys.exit("no insertion point for %s" % k)

p.write_text("\n".join(lines))
print("added %d keys, updated %d" % (added, updated))
