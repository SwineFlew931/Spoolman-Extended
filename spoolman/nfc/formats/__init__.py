"""Tag formats Spoolman knows how to write.

Each format turns a spool into NDEF records. Nothing here touches hardware:
the records go to nfcd already encoded, which is what keeps format knowledge
in one place and the daemon replaceable.

Formats are registered rather than hardcoded into the API so that adding one is
a single new module, and so the write dialog's dropdown and the settings page's
default can both be built from the same list.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from spoolman.api.v1.models import Spool


@dataclass(frozen=True)
class TagRecord:
    """One NDEF record, ready to hand to the daemon."""

    type: str
    payload: bytes
    name: str = ""


@dataclass
class TagPayload:
    """What a format produced for a spool.

    Notes carry anything the user should know before the tag is written — a
    field that had to be dropped, a value that will not survive a round trip.
    They are warnings about content, not errors: a payload with notes is still
    written if the user goes ahead.
    """

    records: list[TagRecord]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildContext:
    """Everything a format needs that is not part of the spool record."""

    serial_id: str = ""
    online_url: str = ""


@dataclass(frozen=True)
class FormatDefinition:
    """A tag format offered in the write dialog."""

    key: str
    label: str
    description: str
    build: Callable[[Spool, BuildContext], TagPayload]
    # False for formats that bind by UID alone and write nothing to the tag.
    writes_tag: bool = True
    # Display order in the write dialog. Set explicitly rather than relying on
    # import order, which linters are free to rearrange.
    order: int = 100


FORMATS: dict[str, FormatDefinition] = {}


def register(definition: FormatDefinition) -> None:
    """Add a format to the registry.

    Args:
        definition: The format to offer.

    """
    FORMATS[definition.key] = definition


def all_formats() -> list[FormatDefinition]:
    """List the registered formats in the order they should be offered.

    Returns:
        list[FormatDefinition]: Every format, most-recommended first.

    """
    return sorted(FORMATS.values(), key=lambda fmt: (fmt.order, fmt.label))


def get(key: str) -> FormatDefinition:
    """Look up a format by key.

    Args:
        key: The format's key.

    Returns:
        FormatDefinition: The format.

    Raises:
        KeyError: No such format.

    """
    if key not in FORMATS:
        raise KeyError(f"Unknown tag format '{key}'.")
    return FORMATS[key]


# Importing each format module is what registers it. This sits at the bottom of
# the file so that the names above already exist when those modules import them.
from spoolman.nfc.formats import (  # noqa: E402
    nfc2klipper,
    openspool,
    opentag3d,
    uid_only,
)

__all__ = ["nfc2klipper", "openspool", "opentag3d", "uid_only"]
