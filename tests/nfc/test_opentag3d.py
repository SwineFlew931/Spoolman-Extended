"""OpenTag3D, checked against bytes read off a real tag.

The fixture is not hand-written: it is the payload the PN532 read from spool
83's tag (Polymaker PolyLite ASA, UID 04BA1457D32A81) on 2026-09-03. If the
offsets ever drift, these tests fail against physical evidence rather than
against someone's reading of the spec.
"""

import base64

from spoolman.api.v1.models import Filament, Spool, Vendor
from spoolman.nfc.formats import BuildContext
from spoolman.nfc.formats import opentag3d as ot

SPOOL_83_PAYLOAD = base64.b64decode(
    "A+hBU0EAAFBvbHlMAAAAAAAAAAAAAAAAAAAAUG9seW1ha2VyAAAAAAAAAEJsYWNrAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAA/wAAAAAAAAAAAAAAAAAG1gPoMhEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMDQPEw==",
)


def _spool(**filament_overrides: object) -> Spool:
    """Build a spool without going through validation, which tests do not need."""
    defaults = {
        "material": "PLA-SG",
        "name": "Starlight Twilight",
        "vendor": Vendor.model_construct(name="Polymaker"),
        "color_hex": "1A2B3C",
        "diameter": 1.75,
        "weight": 1000.0,
        "spool_weight": 140.0,
        "density": 1.24,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 60,
        "extra": {},
    }
    defaults.update(filament_overrides)
    return Spool.model_construct(id=26, filament=Filament.model_construct(**defaults), spool_weight=None)


def test_decodes_the_real_tag_from_spool_83():
    tag = ot.OpenTag3D.unpack(SPOOL_83_PAYLOAD)
    assert tag.tag_version == 1000
    assert tag.base_material == "ASA"
    assert tag.material_modifiers == "PolyL"
    assert tag.manufacturer == "Polymaker"
    assert tag.color_name == "Black"
    assert tuple(tag.color1) == (0, 0, 0, 255)
    assert tag.target_diameter_mm == 1.75
    assert tag.target_weight_g == 1000
    assert tag.print_temp_c == 250
    assert tag.bed_temp_c == 85


def test_decodes_the_extended_block_of_the_real_tag():
    # These four are the ones that confirm the 0xB4-0xB7 offsets.
    tag = ot.OpenTag3D.unpack(SPOOL_83_PAYLOAD)
    assert tag.min_print_temp_c == 240
    assert tag.max_print_temp_c == 260
    assert tag.min_bed_temp_c == 75
    assert tag.max_bed_temp_c == 95


def test_a_short_payload_is_accepted():
    # The real tag is 184 bytes, three short of the full map.
    assert len(SPOOL_83_PAYLOAD) == 184
    assert ot.OpenTag3D.unpack(SPOOL_83_PAYLOAD).manufacturer == "Polymaker"


def test_pack_unpack_round_trips():
    tag = ot.OpenTag3D.unpack(SPOOL_83_PAYLOAD)
    assert ot.OpenTag3D.unpack(tag.pack()).pack() == tag.pack()


def test_the_undocumented_gap_survives_a_round_trip():
    raw = bytearray(SPOOL_83_PAYLOAD.ljust(ot.TOTAL_LEN, b"\x00"))
    raw[ot.RESERVED_GAP] = bytes(range(1, 16))
    tag = ot.OpenTag3D.unpack(bytes(raw))
    assert tag.reserved_gap == bytes(range(1, 16))
    assert tag.pack()[ot.RESERVED_GAP] == bytes(range(1, 16))


def test_material_splitting_keeps_the_suffix():
    # Most six-character names here would otherwise truncate to "PLA-S".
    assert ot.split_material("PLA-SG") == ("PLA", "SG")
    assert ot.split_material("PLA-DC") == ("PLA", "DC")
    assert ot.split_material("ABS-SG") == ("ABS", "SG")
    assert ot.split_material("PETG") == ("PETG", "")
    assert ot.split_material("PLA") == ("PLA", "")
    assert ot.split_material("") == ("", "")
    assert ot.split_material(None) == ("", "")


def test_temperatures_only_survive_in_steps_of_five():
    assert ot.decode_temp(ot.encode_temp(250)) == 250
    assert ot.decode_temp(ot.encode_temp(222)) == 220


def test_a_temperature_that_will_be_rounded_is_flagged():
    payload = ot.from_spool(_spool(settings_extruder_temp=222), BuildContext())
    assert any("222" in note for note in payload.notes)


def test_temperatures_on_the_grid_are_not_flagged():
    payload = ot.from_spool(_spool(settings_extruder_temp=220, settings_bed_temp=60), BuildContext())
    assert payload.notes == []


def test_a_url_that_does_not_fit_is_dropped_not_truncated():
    notes: list[str] = []
    long_url = "http://192.168.0.165:7912/spool/show/26"
    assert len(long_url) > ot.URL_LEN
    assert ot.fit_url(long_url, notes) == ""
    assert notes

    short_url = "http://192.168.0.165:7912/s/26"
    assert len(short_url) <= ot.URL_LEN
    assert ot.fit_url(short_url, []) == short_url


def test_building_from_a_spool_produces_one_record_of_the_right_type():
    payload = ot.from_spool(_spool(), BuildContext(serial_id="1788341713905417"))
    assert len(payload.records) == 1
    record = payload.records[0]
    assert record.type == "application/opentag3d"
    assert len(record.payload) == ot.TOTAL_LEN

    tag = ot.OpenTag3D.unpack(record.payload)
    assert tag.tag_version == 1000
    assert tag.base_material == "PLA"
    assert tag.material_modifiers == "SG"
    assert tag.manufacturer == "Polymaker"
    assert tag.serial_batch_id == "1788341713905417"
    assert tuple(tag.color1) == (0x1A, 0x2B, 0x3C, 255)


def test_a_filaments_own_variant_beats_the_material_suffix():
    payload = ot.from_spool(_spool(extra={"variant": '"Matte"'}), BuildContext())
    assert ot.OpenTag3D.unpack(payload.records[0].payload).material_modifiers == "Matte"


def test_the_generated_serial_fits_the_field_exactly():
    # Microsecond epoch is 16 digits, which is the field width.
    payload = ot.from_spool(_spool(), BuildContext(serial_id="1788341713905417"))
    assert ot.OpenTag3D.unpack(payload.records[0].payload).serial_batch_id == "1788341713905417"
