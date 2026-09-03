"""OpenSpool — JSON, with the extension fields Josh's Snapmaker U1 expects.

Modelled on a tag read from spool 105 on 2026-09-03 rather than on the field
list alone, because the shape has two properties that would have been guessed
wrong:

* **Every value is a string except ``spool_id``**, which is a bare integer.
  ``weight`` and ``diameter`` in particular look numeric and are not.
* **The JSON is compact** — no spaces after separators — and the key order is
  fixed, so a tag written here looks like one written by SpoolFlex.

The observed payload, verbatim::

    {"protocol":"openspool","version":"1.0","brand":"Snapmaker","type":"PLA",
     "subtype":"SnapSpeed","color_hex":"E2DEDB","min_temp":"190","max_temp":"230",
     "bed_min_temp":"25","bed_max_temp":"60","weight":"500","diameter":"1.75",
     "spool_id":1788007331815877}

``additional_color_hexes`` and ``alpha`` are documented as part of what
SpoolFlex writes but appear on neither sampled tag, both of which are
single-colour. ``additional_color_hexes`` has an evident purpose and is emitted
for multi-colour filaments; ``alpha`` is left out entirely, because inventing a
value for a field whose meaning has not been observed risks confusing a reader
that would otherwise have coped with its absence.
"""

import json

from spoolman.api.v1.models import Spool
from spoolman.nfc.formats import BuildContext, FormatDefinition, TagPayload, TagRecord, register
from spoolman.nfc.formats.opentag3d import split_material

MIME_TYPE = "application/json"
PROTOCOL = "openspool"
VERSION = "1.0"


def _color(color_hex: str | None) -> str:
    """Normalise a colour the way the sampled tags carry it.

    Args:
        color_hex: A Spoolman colour, with or without a leading hash.

    Returns:
        str: Uppercase hex with no hash, empty if there is no colour.

    """
    return (color_hex or "").lstrip("#").upper()


def _subtype(spool: Spool, suffix: str) -> str:
    """Work out the product line to put in ``subtype``.

    Args:
        spool: The spool being written.
        suffix: The modifier implied by the material name, e.g. "SG".

    Returns:
        str: The subtype, empty if nothing describes one.

    """
    extra = spool.filament.extra or {}
    for key in ("subtype", "variant"):
        raw = extra.get(key)
        if raw:
            cleaned = str(raw).strip('"').strip()
            if cleaned:
                return cleaned
    return suffix


def _number(value: float | None) -> str:
    """Render a number the way the sampled tags do: as a string, without noise.

    Args:
        value: The value to render.

    Returns:
        str: "500" rather than "500.0", "1.75" kept as it is.

    """
    if value is None:
        return ""
    as_float = float(value)
    return str(int(as_float)) if as_float.is_integer() else str(as_float)


def from_spool(spool: Spool, context: BuildContext) -> TagPayload:
    """Build an OpenSpool payload for a spool.

    Args:
        spool: The spool being written.
        context: Supplies the generated spool id.

    Returns:
        TagPayload: One JSON record, plus notes about anything approximated.

    """
    notes: list[str] = []
    filament = spool.filament
    base, suffix = split_material(filament.material)

    # OpenSpool carries a temperature range; Spoolman stores a single figure
    # for each. Writing the one value as both ends is honest about what is
    # known, and is what the printer will then hold to. That is true of every
    # write, so it belongs in the format's description rather than in a note
    # the user would learn to ignore.
    nozzle = filament.settings_extruder_temp
    bed = filament.settings_bed_temp

    missing = [
        name
        for name, present in (
            ("a nozzle temperature", nozzle),
            ("a bed temperature", bed),
            ("a colour", filament.color_hex),
        )
        if not present
    ]
    if missing:
        notes.append(f"This filament has no {', no '.join(missing)}, so the tag will carry empty values there.")

    document: dict[str, object] = {
        "protocol": PROTOCOL,
        "version": VERSION,
        "brand": filament.vendor.name if filament.vendor else "",
        "type": base or (filament.material or ""),
        "subtype": _subtype(spool, suffix),
        "color_hex": _color(filament.color_hex),
        "min_temp": _number(nozzle),
        "max_temp": _number(nozzle),
        "bed_min_temp": _number(bed),
        "bed_max_temp": _number(bed),
        "weight": _number(filament.weight),
        "diameter": _number(filament.diameter),
    }
    if context.serial_id:
        document["spool_id"] = int(context.serial_id)
    if not document["subtype"]:
        notes.append(
            "Nothing on this filament says which product line it is, so subtype will be empty. "
            "Set the filament's subtype or variant field if the printer should see it.",
        )
    if filament.multi_color_hexes:
        extras = [_color(part) for part in filament.multi_color_hexes.split(",") if part.strip()]
        if extras:
            document["additional_color_hexes"] = extras

    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return TagPayload(records=[TagRecord(type=MIME_TYPE, payload=encoded)], notes=notes)


register(
    FormatDefinition(
        key="openspool",
        label="OpenSpool",
        description=(
            "JSON, with the Snapmaker U1 extension fields. Confirmed readable by the U1. "
            "Carries a temperature range, so Spoolman's single nozzle and bed figures are "
            "written as both ends of it."
        ),
        build=from_spool,
        order=20,
    ),
)
