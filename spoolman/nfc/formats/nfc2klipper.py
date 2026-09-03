"""nfc2klipper — an NDEF Text record holding nothing but Spoolman's own ids.

    SPOOL:3
    FILAMENT:2

Two lines, no payload of substance: the tag is a pointer and Spoolman remains
the source of truth. That makes it the smallest format offered here by a wide
margin, and the only one whose content never goes stale when a spool is edited.

The record is a well-known Text record, whose payload is a status byte carrying
the language-code length, then the language code, then the text. Building it by
hand rather than with ndeflib is deliberate: it keeps the encoder out of
Spoolman's dependencies, and the format is three lines of a stable spec.
"""

from spoolman.api.v1.models import Spool
from spoolman.nfc.formats import BuildContext, FormatDefinition, TagPayload, TagRecord, register

RECORD_TYPE = "urn:nfc:wkt:T"
LANGUAGE = "en"

# Bit 7 of the status byte selects the encoding: 0 for UTF-8. Bits 5-0 hold the
# length of the language code, so a two-letter code is simply the value 2.
UTF8_STATUS = 0x00


def encode_text(text: str, language: str = LANGUAGE) -> bytes:
    """Encode an NDEF Text record payload.

    Args:
        text: The text to carry.
        language: IANA language code for it.

    Returns:
        bytes: The record payload.

    """
    code = language.encode("ascii")
    return bytes([UTF8_STATUS | len(code)]) + code + text.encode("utf-8")


def decode_text(payload: bytes) -> str:
    """Decode an NDEF Text record payload.

    Args:
        payload: The record payload.

    Returns:
        str: The text, without the language prefix.

    """
    if not payload:
        return ""
    language_length = payload[0] & 0x3F
    return payload[1 + language_length :].decode("utf-8", "replace")


def from_spool(spool: Spool, _context: BuildContext) -> TagPayload:
    """Build an nfc2klipper payload for a spool.

    Args:
        spool: The spool being written.
        _context: Unused; this format carries no generated identifiers.

    Returns:
        TagPayload: One text record.

    """
    text = f"SPOOL:{spool.id}\nFILAMENT:{spool.filament.id}"
    return TagPayload(records=[TagRecord(type=RECORD_TYPE, payload=encode_text(text))])


register(
    FormatDefinition(
        key="nfc2klipper",
        label="nfc2klipper",
        description=(
            "A plain text pointer to Spoolman's spool and filament ids. Tiny, fits any tag, "
            "and never goes stale when you edit the spool — but it is only meaningful to "
            "software that can reach this Spoolman."
        ),
        build=from_spool,
        order=30,
    ),
)
