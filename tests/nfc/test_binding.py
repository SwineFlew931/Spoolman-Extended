"""Extra-field encoding and the card_uids list.

The database-backed half of binding.py is exercised against the real instance
rather than here; these cover the encoding rules, which are where the silent
mistakes live.
"""

from spoolman.nfc import binding
from spoolman.nfc.identifiers import normalise_uid

# As stored on the real instance: a JSON-encoded string, quotes included.
STORED_SINGLE = '"04BA1457D32A81"'
STORED_PAIR = '"04BA1457D32A81,04B91457D32A81"'


def test_a_stored_uid_is_json_encoded_not_bare():
    assert binding.decode_value(STORED_SINGLE) == "04BA1457D32A81"
    assert binding.encode_value("04BA1457D32A81") == STORED_SINGLE


def test_an_encoded_empty_string_is_not_the_two_quote_characters():
    assert binding.decode_value('""') == ""
    assert binding.encode_value("") == '""'


def test_an_integer_field_stores_without_quotes():
    # printer_name and mmu_gate_map are written by other systems in this shape.
    assert binding.encode_value(-1) == "-1"
    assert binding.decode_value("-1") == -1


def test_a_field_that_was_never_encoded_is_still_readable():
    assert binding.decode_value("04BA1457D32A81") == "04BA1457D32A81"


def test_uids_are_normalised_however_they_arrive():
    assert normalise_uid("04:BB:14:57:D3:2A:81") == "04BB1457D32A81"
    assert normalise_uid("04-bb-14-57-d3-2a-81") == "04BB1457D32A81"
    assert normalise_uid("04 bb 14 57 d3 2a 81") == "04BB1457D32A81"
    assert normalise_uid(bytes.fromhex("04BB1457D32A81")) == "04BB1457D32A81"


def test_parsing_an_unset_field_gives_an_empty_list():
    assert binding.parse_card_uids(None) == []
    assert binding.parse_card_uids({}) == []
    assert binding.parse_card_uids({"card_uids": '""'}) == []


def test_parsing_a_comma_separated_list():
    assert binding.parse_card_uids({"card_uids": STORED_PAIR}) == ["04BA1457D32A81", "04B91457D32A81"]


def test_parsing_accepts_the_orm_shape_too():
    class Row:
        def __init__(self, key: str, value: str) -> None:
            self.key = key
            self.value = value

    assert binding.parse_card_uids([Row("card_uids", STORED_SINGLE)]) == ["04BA1457D32A81"]


def test_adding_a_uid_appends_rather_than_replaces():
    # SpoolLink and Happy Hare write the same records, so replacing loses data.
    result = binding.with_uid_added({"card_uids": STORED_SINGLE}, "04B91457D32A81")
    assert binding.decode_value(result) == "04BA1457D32A81,04B91457D32A81"


def test_adding_a_uid_twice_is_a_no_op():
    once = binding.with_uid_added({"card_uids": STORED_SINGLE}, "04BA1457D32A81")
    assert binding.decode_value(once) == "04BA1457D32A81"


def test_adding_normalises_before_comparing():
    result = binding.with_uid_added({"card_uids": STORED_SINGLE}, "04:ba:14:57:d3:2a:81")
    assert binding.decode_value(result) == "04BA1457D32A81"


def test_adding_to_an_empty_field():
    assert binding.decode_value(binding.with_uid_added({}, "04BA1457D32A81")) == "04BA1457D32A81"


def test_removing_leaves_the_others_alone():
    result = binding.with_uid_removed({"card_uids": STORED_PAIR}, "04BA1457D32A81")
    assert binding.decode_value(result) == "04B91457D32A81"


def test_removing_the_last_uid_leaves_an_encoded_empty_string():
    result = binding.with_uid_removed({"card_uids": STORED_SINGLE}, "04BA1457D32A81")
    assert result == '""'


def test_removing_something_that_is_not_there_changes_nothing():
    result = binding.with_uid_removed({"card_uids": STORED_SINGLE}, "04111457D32A81")
    assert binding.decode_value(result) == "04BA1457D32A81"


def test_other_systems_fields_are_never_in_the_patch():
    # Only card_uids is ever written back, so printer_name and mmu_gate_map
    # cannot be clobbered by a bind.
    extra = {"card_uids": STORED_SINGLE, "printer_name": '"U1"', "mmu_gate_map": "-1"}
    assert binding.with_uid_added(extra, "04B91457D32A81") == '"04BA1457D32A81,04B91457D32A81"'
