"""NFC+ — bind by UID and write nothing at all.

The tag's factory UID is the whole identifier; everything else stays in
Spoolman. Nothing is written, so any tag works regardless of capacity, a
write cannot fail, and a tag already carrying someone else's data keeps it.

The trade-off is that the tag means nothing away from this Spoolman instance,
and that the binding rests entirely on a UID from a 256-value space — which is
why duplicate detection matters more for this format than for any other.
"""

from spoolman.api.v1.models import Spool
from spoolman.nfc.formats import BuildContext, FormatDefinition, TagPayload, register


def from_spool(_spool: Spool, _context: BuildContext) -> TagPayload:
    """Produce the empty payload that is this format's whole point.

    Args:
        _spool: Unused; nothing about the spool is written to the tag.
        _context: Unused.

    Returns:
        TagPayload: No records.

    """
    return TagPayload(records=[])


register(
    FormatDefinition(
        key="uid_only",
        label="NFC+ (UID only)",
        description=(
            "Writes nothing to the tag and binds its UID to this spool. Works with any tag, "
            "including one that already holds another format's data."
        ),
        build=from_spool,
        order=40,
        writes_tag=False,
    ),
)
