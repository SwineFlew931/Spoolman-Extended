"""How much room a tag payload needs, and which chips will hold it.

Two different questions get answered with these numbers, and only one of them
is authoritative:

1. *What tag should I reach for?* Answered here, before a tag is presented, by
   sizing the payload for the spool about to be written and comparing it with
   the published capacity of each NTAG chip. Advisory.
2. *Will this tag hold it?* Answered by the tag itself at write time, by
   reading ``tag.ndef.capacity``. That is the only trustworthy answer, because
   a tag's advertised capacity is not always its real one — the NTAG216 clones
   in use here claim 872 bytes in their capability container and actually hold
   888. nfcd performs that check and refuses a write that will not fit.

The unit throughout is the length of the encoded NDEF *message*, excluding the
TLV wrapper that carries it. That is deliberate: it is what nfcpy's
``ndef.capacity`` is measured in, so the two can be compared directly.
"""

from dataclasses import dataclass

# An NDEF record's fixed overhead, for a record with no ID field: the header
# byte, the type-length byte and the payload-length byte. Payloads of 256 bytes
# or more cannot use the short form, and spend four bytes on the length instead
# of one.
SHORT_RECORD_OVERHEAD = 3
LONG_RECORD_EXTRA = 3
SHORT_RECORD_MAX_PAYLOAD = 255

# What the TLV wrapper costs inside a tag's NDEF area: one type byte plus a
# length field, which is three bytes for anything a spool payload might reach.
# Deducting the worst case keeps the recommendation honest rather than
# optimistic at the boundary.
TLV_OVERHEAD = 4


@dataclass(frozen=True)
class Chip:
    """An NTAG variant and its published NDEF area."""

    name: str
    user_memory: int

    @property
    def message_capacity(self) -> int:
        """The largest NDEF message this chip can be expected to hold.

        Returns:
            int: Capacity in bytes, TLV overhead already deducted.

        """
        return self.user_memory - TLV_OVERHEAD


# Every NTAG21x is ISO14443A Type 2 and protocol-compatible with all the
# formats offered here, so fit is purely a question of room. The two small
# chips are listed rather than omitted so that a user holding one is told it is
# unsuitable instead of not finding it at all.
CHIPS: tuple[Chip, ...] = (
    Chip("NTAG210", 48),
    Chip("NTAG212", 128),
    Chip("NTAG213", 144),
    Chip("NTAG215", 504),
    Chip("NTAG216", 888),
)


@dataclass(frozen=True)
class ChipFit:
    """Whether one chip can hold a particular payload."""

    name: str
    capacity: int
    fits: bool
    headroom: int


def record_length(record_type: str, payload_length: int) -> int:
    """Size one NDEF record as encoded, including its header.

    Args:
        record_type: The record's type string, e.g. "application/opentag3d".
        payload_length: Length of the record's payload in bytes.

    Returns:
        int: Encoded length in bytes.

    """
    overhead = SHORT_RECORD_OVERHEAD
    if payload_length > SHORT_RECORD_MAX_PAYLOAD:
        overhead += LONG_RECORD_EXTRA
    return overhead + len(record_type.encode("utf-8")) + payload_length


def message_length(records: list[tuple[str, int]]) -> int:
    """Size a whole NDEF message.

    Args:
        records: One (record_type, payload_length) pair per record.

    Returns:
        int: Encoded length in bytes.

    """
    return sum(record_length(rtype, length) for rtype, length in records)


def recommend(size: int) -> list[ChipFit]:
    """Say which chips will hold a message of this size.

    Args:
        size: Encoded message length in bytes.

    Returns:
        list[ChipFit]: One entry per known chip, smallest first.

    """
    return [
        ChipFit(
            name=chip.name,
            capacity=chip.message_capacity,
            fits=size <= chip.message_capacity,
            headroom=chip.message_capacity - size,
        )
        for chip in CHIPS
    ]


def fits(size: int, tag_capacity: int | None) -> bool:
    """Check a message against the capacity a real tag reported.

    Args:
        size: Encoded message length in bytes.
        tag_capacity: What the tag said it can hold, or None if it did not say.

    Returns:
        bool: Whether the write should be attempted.

    """
    if not tag_capacity:
        # A tag that will not say is not evidence either way; let the write be
        # attempted and fail honestly rather than refusing on a guess.
        return True
    return size <= tag_capacity
