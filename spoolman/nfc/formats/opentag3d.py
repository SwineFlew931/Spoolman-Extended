"""OpenTag3D — a fixed binary memory map, not a serialisation format.

Offsets were validated byte for byte against a real tag (spool 83, Polymaker
PolyLite ASA) read with the PN532, and the fixture in the tests is that tag's
own bytes. Three things about this layout are easy to get wrong:

* **0x0C-0x1A is a 15-byte region the published field table does not account
  for.** It is all zero on the observed tags. Whatever is there is preserved on
  read and written as zeros on create, rather than guessed at.
* **Temperatures are stored divided by five**, so only multiples of five
  survive a round trip. Values are rounded to nearest on write and the caller
  is told when that changed something.
* **tag_version is written as 1000, not 1003.** The tag Josh's U1 already reads
  carries 1000, so that is what is matched.

The Core block ends at 0x70 and fits an NTAG213. The Extended block runs to
0xBA and needs an NTAG215 or larger.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from spoolman.api.v1.models import Spool
from spoolman.nfc.formats import BuildContext, FormatDefinition, TagPayload, TagRecord, register

logger = logging.getLogger(__name__)

MIME_TYPE = "application/opentag3d"
CORE_LEN = 0x70
TOTAL_LEN = 0xBB  # through the last Extended field at 0xBA

# Field widths that content has to be fitted into, named because the fitting
# rules below only make sense next to them.
MATERIAL_LEN = 5
MANUFACTURER_LEN = 16
COLOR_NAME_LEN = 32
URL_LEN = 32
SERIAL_LEN = 16

RESERVED_GAP = slice(0x0C, 0x1B)
RESERVED_GAP_LEN = 15

TEMP_SCALE = 5
RGBA_LEN = 4
HEX_RGB_LEN = 6
HEX_RGBA_LEN = 8


def _u16(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 2], "big")


def _put_u16(buf: bytearray, offset: int, value: int | None) -> None:
    buf[offset : offset + 2] = max(0, min(0xFFFF, int(value or 0))).to_bytes(2, "big")


def _put_u8(buf: bytearray, offset: int, value: int | None) -> None:
    buf[offset] = max(0, min(0xFF, int(value or 0)))


def _text(raw: bytes, offset: int, length: int) -> str:
    return raw[offset : offset + length].split(b"\x00")[0].decode("utf-8", "replace").strip()


def _put_text(buf: bytearray, offset: int, length: int, value: str | None) -> None:
    encoded = (value or "").encode("utf-8")[:length]
    buf[offset : offset + length] = encoded + b"\x00" * (length - len(encoded))


def encode_temp(celsius: float | None) -> int:
    """Encode a temperature into the tag's units.

    Args:
        celsius: Temperature in degrees Celsius.

    Returns:
        int: The stored value, which is degrees divided by five.

    """
    return 0 if not celsius else round(float(celsius) / TEMP_SCALE)


def decode_temp(stored: int) -> int:
    """Decode a temperature from the tag's units.

    Args:
        stored: The value as stored.

    Returns:
        int: Temperature in degrees Celsius.

    """
    return stored * TEMP_SCALE


@dataclass
class OpenTag3D:
    """The full memory map, as fields."""

    tag_version: int = 1000
    base_material: str = ""  # 0x02, 5 bytes
    material_modifiers: str = ""  # 0x07, 5 bytes
    manufacturer: str = ""  # 0x1B, 16 bytes
    color_name: str = ""  # 0x2B, 32 bytes
    color1: tuple[int, ...] = (0, 0, 0, 255)  # 0x4B, RGBA
    color2: tuple[int, ...] = (0, 0, 0, 0)  # 0x50
    color3: tuple[int, ...] = (0, 0, 0, 0)  # 0x54
    color4: tuple[int, ...] = (0, 0, 0, 0)  # 0x58
    target_diameter_mm: float = 0.0  # 0x5C, mm x1000
    target_weight_g: int = 0  # 0x5E, grams
    print_temp_c: int = 0  # 0x60, C/5
    bed_temp_c: int = 0  # 0x61, C/5
    density: float = 0.0  # 0x62, g/cm3 x1000
    td_mm: float = 0.0  # 0x64, mm x10
    # -- Extended block, needs NTAG215 or larger --
    online_url: str = ""  # 0x70, 32 bytes ASCII
    serial_batch_id: str = ""  # 0x90, 16 bytes, where the generated id goes
    spool_core_diameter_mm: int = 0  # 0xA7
    empty_spool_weight_g: int = 0  # 0xAC
    max_dry_temp_c: int = 0  # 0xB2
    dry_time_hr: int = 0  # 0xB3
    min_print_temp_c: int = 0  # 0xB4
    max_print_temp_c: int = 0  # 0xB5
    min_bed_temp_c: int = 0  # 0xB6
    max_bed_temp_c: int = 0  # 0xB7
    # The undocumented gap at 0x0C, preserved verbatim across a read/write.
    reserved_gap: bytes = field(default=b"\x00" * RESERVED_GAP_LEN, repr=False)

    def pack(self) -> bytes:
        """Render the memory map to bytes.

        Returns:
            bytes: TOTAL_LEN bytes, ready to be the record payload.

        """
        buf = bytearray(TOTAL_LEN)
        _put_u16(buf, 0x00, self.tag_version)
        _put_text(buf, 0x02, MATERIAL_LEN, self.base_material)
        _put_text(buf, 0x07, MATERIAL_LEN, self.material_modifiers)
        gap = (self.reserved_gap or b"\x00" * RESERVED_GAP_LEN)[:RESERVED_GAP_LEN]
        buf[RESERVED_GAP] = gap.ljust(RESERVED_GAP_LEN, b"\x00")
        _put_text(buf, 0x1B, MANUFACTURER_LEN, self.manufacturer)
        _put_text(buf, 0x2B, COLOR_NAME_LEN, self.color_name)
        for offset, color in ((0x4B, self.color1), (0x50, self.color2), (0x54, self.color3), (0x58, self.color4)):
            buf[offset : offset + RGBA_LEN] = bytes(max(0, min(255, int(c))) for c in color)
        _put_u16(buf, 0x5C, round((self.target_diameter_mm or 0) * 1000))
        _put_u16(buf, 0x5E, self.target_weight_g)
        _put_u8(buf, 0x60, encode_temp(self.print_temp_c))
        _put_u8(buf, 0x61, encode_temp(self.bed_temp_c))
        _put_u16(buf, 0x62, round((self.density or 0) * 1000))
        _put_u16(buf, 0x64, round((self.td_mm or 0) * 10))
        _put_text(buf, 0x70, URL_LEN, self.online_url)
        _put_text(buf, 0x90, SERIAL_LEN, self.serial_batch_id)
        _put_u8(buf, 0xA7, self.spool_core_diameter_mm)
        _put_u16(buf, 0xAC, self.empty_spool_weight_g)
        _put_u8(buf, 0xB2, encode_temp(self.max_dry_temp_c))
        _put_u8(buf, 0xB3, self.dry_time_hr)
        _put_u8(buf, 0xB4, encode_temp(self.min_print_temp_c))
        _put_u8(buf, 0xB5, encode_temp(self.max_print_temp_c))
        _put_u8(buf, 0xB6, encode_temp(self.min_bed_temp_c))
        _put_u8(buf, 0xB7, encode_temp(self.max_bed_temp_c))
        return bytes(buf)

    @classmethod
    def unpack(cls, raw: bytes) -> "OpenTag3D":
        """Read a memory map back out of bytes.

        Short payloads are accepted and zero-padded: real tags are written by
        several different tools and not all of them fill the Extended block.

        Args:
            raw: The record payload.

        Returns:
            OpenTag3D: The decoded fields.

        """
        buf = bytes(raw).ljust(TOTAL_LEN, b"\x00")
        return cls(
            tag_version=_u16(buf, 0x00),
            base_material=_text(buf, 0x02, MATERIAL_LEN),
            material_modifiers=_text(buf, 0x07, MATERIAL_LEN),
            manufacturer=_text(buf, 0x1B, MANUFACTURER_LEN),
            color_name=_text(buf, 0x2B, COLOR_NAME_LEN),
            color1=tuple(buf[0x4B:0x4F]),
            color2=tuple(buf[0x50:0x54]),
            color3=tuple(buf[0x54:0x58]),
            color4=tuple(buf[0x58:0x5C]),
            target_diameter_mm=_u16(buf, 0x5C) / 1000,
            target_weight_g=_u16(buf, 0x5E),
            print_temp_c=decode_temp(buf[0x60]),
            bed_temp_c=decode_temp(buf[0x61]),
            density=_u16(buf, 0x62) / 1000,
            td_mm=_u16(buf, 0x64) / 10,
            online_url=_text(buf, 0x70, URL_LEN),
            serial_batch_id=_text(buf, 0x90, SERIAL_LEN),
            spool_core_diameter_mm=buf[0xA7],
            empty_spool_weight_g=_u16(buf, 0xAC),
            max_dry_temp_c=decode_temp(buf[0xB2]),
            dry_time_hr=buf[0xB3],
            min_print_temp_c=decode_temp(buf[0xB4]),
            max_print_temp_c=decode_temp(buf[0xB5]),
            min_bed_temp_c=decode_temp(buf[0xB6]),
            max_bed_temp_c=decode_temp(buf[0xB7]),
            reserved_gap=buf[RESERVED_GAP],
        )

    def as_dict(self) -> dict[str, Any]:
        """Render the fields for display.

        Returns:
            dict[str, Any]: Every public field, plus colour 1 as a hex string.

        """
        out = {k: v for k, v in self.__dict__.items() if k != "reserved_gap"}
        red, green, blue = self.color1[:3]
        out["color1_hex"] = f"{red:02X}{green:02X}{blue:02X}"
        return out


def hex_to_rgba(color_hex: str | None, alpha: int = 255) -> tuple[int, ...]:
    """Convert a Spoolman colour to the tag's RGBA quad.

    Args:
        color_hex: A hex colour, with or without a leading hash, RGB or RGBA.
        alpha: Alpha to use when the colour does not carry one.

    Returns:
        tuple[int, ...]: Four channel values.

    """
    if not color_hex:
        return (0, 0, 0, alpha)
    text = color_hex.lstrip("#")
    if len(text) == HEX_RGBA_LEN:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4, 6))
    if len(text) != HEX_RGB_LEN:
        return (0, 0, 0, alpha)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), alpha)


def split_material(material: str | None) -> tuple[str, str]:
    """Split a Spoolman material name into the tag's base and modifier fields.

    base_material is only five bytes, and most of the six-character names in
    use — PLA-SG, PLA-DC, ABS-SG — would truncate to "PLA-S" and lose the
    distinction entirely. The suffix goes to material_modifiers instead, which
    is what that field is for.

    Args:
        material: The Spoolman material name.

    Returns:
        tuple[str, str]: Base material and modifier, each already fitted.

    """
    raw = (material or "").strip()
    if not raw:
        return "", ""
    for separator in ("-", "_", " "):
        if separator in raw:
            base, _, rest = raw.partition(separator)
            return base[:MATERIAL_LEN], rest.replace(separator, "")[:MATERIAL_LEN]
    return raw[:MATERIAL_LEN], ""


def fit_url(url: str, notes: list[str]) -> str:
    """Keep a URL only if it fits whole.

    A truncated URL is worse than an absent one: cutting
    "http://host:7912/spool/show/26" at 32 bytes leaves something that resolves
    to the wrong page.

    Args:
        url: The URL to store.
        notes: Collects a note when the URL has to be dropped.

    Returns:
        str: The URL, or an empty string if it will not fit.

    """
    url = (url or "").strip()
    if not url:
        return ""
    if len(url.encode("utf-8")) > URL_LEN:
        notes.append(
            f"The spool's URL is {len(url)} characters and the tag's field holds {URL_LEN}, "
            f"so it has been left off rather than written truncated.",
        )
        return ""
    return url


def _modifier_for(spool: Spool, suffix: str) -> str:
    """Pick the modifier field's value.

    A filament's own variant or subtype wins over whatever the material name
    implies, since it was entered deliberately.

    Args:
        spool: The spool being written.
        suffix: The modifier implied by the material name.

    Returns:
        str: The modifier, fitted to the field.

    """
    extra = spool.filament.extra or {}
    for key in ("variant", "subtype"):
        raw = extra.get(key)
        if raw:
            cleaned = str(raw).strip('"').strip()
            if cleaned:
                return cleaned[:MATERIAL_LEN]
    return suffix[:MATERIAL_LEN]


def _note_rounded_temps(values: dict[str, int | None], notes: list[str]) -> None:
    """Warn about temperatures that will not survive a round trip.

    Args:
        values: Named temperatures in degrees Celsius.
        notes: Collects one note listing everything that had to be rounded.

    """
    rounded = {
        name: (value, decode_temp(encode_temp(value)))
        for name, value in values.items()
        if value and decode_temp(encode_temp(value)) != value
    }
    if rounded:
        detail = ", ".join(f"{name} {was} → {now} °C" for name, (was, now) in rounded.items())
        notes.append(f"This format stores temperatures in steps of {TEMP_SCALE} °C, so {detail}.")


def from_spool(spool: Spool, context: BuildContext) -> TagPayload:
    """Build an OpenTag3D payload for a spool.

    Args:
        spool: The spool being written.
        context: The generated serial and the URL to point at.

    Returns:
        TagPayload: One record, plus any notes about content that had to give.

    """
    notes: list[str] = []
    filament = spool.filament
    base, suffix = split_material(filament.material)

    _note_rounded_temps(
        {"nozzle": filament.settings_extruder_temp, "bed": filament.settings_bed_temp},
        notes,
    )
    if filament.material and not base:
        notes.append("This filament has no material set, so the tag will not say what it is.")

    tag = OpenTag3D(
        base_material=base,
        material_modifiers=_modifier_for(spool, suffix),
        manufacturer=(filament.vendor.name if filament.vendor else "")[:MANUFACTURER_LEN],
        color_name=(filament.name or "")[:COLOR_NAME_LEN],
        color1=hex_to_rgba(filament.color_hex),
        target_diameter_mm=filament.diameter or 0,
        target_weight_g=int(filament.weight or 0),
        print_temp_c=filament.settings_extruder_temp or 0,
        bed_temp_c=filament.settings_bed_temp or 0,
        density=filament.density or 0,
        empty_spool_weight_g=int(spool.spool_weight or filament.spool_weight or 0),
        serial_batch_id=context.serial_id[:SERIAL_LEN],
        online_url=fit_url(context.online_url, notes),
    )
    return TagPayload(records=[TagRecord(type=MIME_TYPE, payload=tag.pack())], notes=notes)


register(
    FormatDefinition(
        key="opentag3d",
        label="OpenTag3D",
        description="Binary memory map. Confirmed readable by the Snapmaker U1.",
        build=from_spool,
        order=10,
    ),
)
