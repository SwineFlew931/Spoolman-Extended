"""OpenSpool, checked against a tag SpoolFlex actually wrote.

The fixture is the payload read from spool 105 (Snapmaker SnapSpeed White, UID
04411457D32A81) on 2026-09-03. What matters most here is shape rather than
content: key order, and which values are strings.
"""

import base64
import json

from spoolman.api.v1.models import Filament, Spool, Vendor
from spoolman.nfc.formats import BuildContext
from spoolman.nfc.formats import openspool as os_fmt

SPOOL_105_PAYLOAD = base64.b64decode(
    "eyJwcm90b2NvbCI6Im9wZW5zcG9vbCIsInZlcnNpb24iOiIxLjAiLCJicmFuZCI6IlNuYXBtYWtlciIsInR5cGUiOiJQTEEiLCJz"
    "dWJ0eXBlIjoiU25hcFNwZWVkIiwiY29sb3JfaGV4IjoiRTJERURCIiwibWluX3RlbXAiOiIxOTAiLCJtYXhfdGVtcCI6IjIzMCIs"
    "ImJlZF9taW5fdGVtcCI6IjI1IiwiYmVkX21heF90ZW1wIjoiNjAiLCJ3ZWlnaHQiOiI1MDAiLCJkaWFtZXRlciI6IjEuNzUiLCJz"
    "cG9vbF9pZCI6MTc4ODAwNzMzMTgxNTg3N30=",
)


def _spool(**filament_overrides: object) -> Spool:
    """Build spool 105 as Spoolman holds it, without going through validation."""
    defaults = {
        "material": "PLA",
        "name": "SnapSpeed White",
        "vendor": Vendor.model_construct(name="Snapmaker"),
        "color_hex": "E2DEDB",
        "diameter": 1.75,
        "weight": 500.0,
        "density": 1.24,
        "settings_extruder_temp": 220,
        "settings_bed_temp": 60,
        "multi_color_hexes": None,
        # Stored as an encoded empty string on the real instance, which is not
        # the same as the two-character string it looks like.
        "extra": {"variant": '""'},
    }
    defaults.update(filament_overrides)
    return Spool.model_construct(id=105, filament=Filament.model_construct(**defaults))


def test_the_real_tag_is_the_shape_this_module_assumes():
    document = json.loads(SPOOL_105_PAYLOAD)
    assert document["protocol"] == "openspool"
    assert document["version"] == "1.0"
    # Everything is a string except spool_id, which is a bare integer.
    assert isinstance(document["spool_id"], int)
    assert all(isinstance(v, str) for k, v in document.items() if k != "spool_id")
    assert isinstance(document["weight"], str)
    assert isinstance(document["diameter"], str)


def test_key_order_matches_the_real_tag():
    real_order = list(json.loads(SPOOL_105_PAYLOAD).keys())
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext(serial_id="1788007331815877")).records[0].payload)
    assert list(built.keys()) == real_order


def test_the_json_is_compact_like_the_real_tag():
    assert b", " not in SPOOL_105_PAYLOAD
    payload = os_fmt.from_spool(_spool(), BuildContext(serial_id="1")).records[0].payload
    assert b", " not in payload
    assert b'": ' not in payload


def test_values_are_strings_except_the_spool_id():
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext(serial_id="1788007331815877")).records[0].payload)
    assert built["spool_id"] == 1788007331815877
    assert isinstance(built["spool_id"], int)
    assert all(isinstance(v, str) for k, v in built.items() if k != "spool_id")


def test_weights_do_not_pick_up_a_decimal_point():
    # Spoolman stores 500.0; the tag should say "500", as the real one does.
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext()).records[0].payload)
    assert built["weight"] == "500"
    assert built["diameter"] == "1.75"


def test_the_record_type_matches_the_real_tag():
    record = os_fmt.from_spool(_spool(), BuildContext()).records[0]
    assert record.type == "application/json"


def test_an_encoded_empty_extra_field_is_treated_as_empty():
    # extra values are JSON-encoded strings, so '""' means "not set".
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext()).records[0].payload)
    assert built["subtype"] == ""


def test_a_real_subtype_is_used_when_one_is_set():
    built = json.loads(os_fmt.from_spool(_spool(extra={"subtype": '"SnapSpeed"'}), BuildContext()).records[0].payload)
    assert built["subtype"] == "SnapSpeed"


def test_a_material_suffix_becomes_the_subtype_when_nothing_better_exists():
    built = json.loads(os_fmt.from_spool(_spool(material="PLA-SG", extra={}), BuildContext()).records[0].payload)
    assert built["type"] == "PLA"
    assert built["subtype"] == "SG"


def test_a_missing_subtype_is_flagged():
    payload = os_fmt.from_spool(_spool(), BuildContext())
    assert any("subtype" in note for note in payload.notes)


def test_the_single_temperature_is_written_as_both_ends_of_the_range():
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext()).records[0].payload)
    assert built["min_temp"] == "220"
    assert built["max_temp"] == "220"
    assert built["bed_min_temp"] == "60"
    assert built["bed_max_temp"] == "60"


def test_missing_values_are_flagged_rather_than_invented():
    payload = os_fmt.from_spool(_spool(settings_extruder_temp=None, color_hex=None), BuildContext())
    note = " ".join(payload.notes)
    assert "nozzle temperature" in note
    assert "colour" in note
    built = json.loads(payload.records[0].payload)
    assert built["min_temp"] == ""
    assert built["color_hex"] == ""


def test_colours_are_uppercase_without_a_hash():
    built = json.loads(os_fmt.from_spool(_spool(color_hex="#e2dedb"), BuildContext()).records[0].payload)
    assert built["color_hex"] == "E2DEDB"


def test_multi_colour_filaments_carry_the_extra_hexes():
    built = json.loads(
        os_fmt.from_spool(_spool(multi_color_hexes="aabbcc,ddeeff"), BuildContext()).records[0].payload,
    )
    assert built["additional_color_hexes"] == ["AABBCC", "DDEEFF"]


def test_single_colour_filaments_omit_the_extra_hexes_like_the_real_tag():
    assert "additional_color_hexes" not in json.loads(SPOOL_105_PAYLOAD)
    built = json.loads(os_fmt.from_spool(_spool(), BuildContext()).records[0].payload)
    assert "additional_color_hexes" not in built


def test_the_payload_is_close_in_size_to_the_real_one():
    # The real tag is 251 bytes; ours differs only in subtype and temperatures.
    payload = os_fmt.from_spool(_spool(extra={"subtype": '"SnapSpeed"'}), BuildContext(serial_id="1788007331815877"))
    assert abs(len(payload.records[0].payload) - len(SPOOL_105_PAYLOAD)) < 20
