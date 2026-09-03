"""The format registry, and the two formats small enough to check whole."""

import pytest

from spoolman.api.v1.models import Filament, Spool, Vendor
from spoolman.nfc import capacity
from spoolman.nfc.formats import BuildContext, all_formats, get
from spoolman.nfc.formats import nfc2klipper as klipper


def _spool() -> Spool:
    return Spool.model_construct(
        id=3,
        filament=Filament.model_construct(
            id=2,
            material="PLA",
            name="Starlight Twilight",
            vendor=Vendor.model_construct(name="Polymaker"),
            color_hex="1A2B3C",
            diameter=1.75,
            weight=1000.0,
            density=1.24,
            settings_extruder_temp=220,
            settings_bed_temp=60,
            multi_color_hexes=None,
            extra={},
        ),
    )


def test_every_registered_format_is_offered_in_a_deliberate_order():
    keys = [fmt.key for fmt in all_formats()]
    assert keys == ["opentag3d", "openspool", "nfc2klipper", "uid_only"]


def test_the_confirmed_formats_come_first():
    # OpenTag3D and OpenSpool are the two read by Josh's U1, so they lead.
    assert [fmt.key for fmt in all_formats()][:2] == ["opentag3d", "openspool"]


def test_an_unknown_format_is_a_clear_error():
    with pytest.raises(KeyError, match="bambu"):
        get("bambu")


def test_every_format_builds_something_for_a_normal_spool():
    for fmt in all_formats():
        payload = fmt.build(_spool(), BuildContext(serial_id="1788341713905417"))
        assert isinstance(payload.records, list)
        if fmt.writes_tag:
            assert payload.records, f"{fmt.key} claims to write a tag but produced no records"
        else:
            assert not payload.records


def test_nfc2klipper_carries_both_ids():
    payload = klipper.from_spool(_spool(), BuildContext())
    assert klipper.decode_text(payload.records[0].payload) == "SPOOL:3\nFILAMENT:2"


def test_nfc2klipper_uses_a_well_known_text_record():
    record = klipper.from_spool(_spool(), BuildContext()).records[0]
    assert record.type == "urn:nfc:wkt:T"
    # Status byte holds the language length, then the code, then the text.
    assert record.payload[0] == 2
    assert record.payload[1:3] == b"en"


def test_nfc2klipper_round_trips_through_its_own_encoder():
    assert klipper.decode_text(klipper.encode_text("SPOOL:1\nFILAMENT:9")) == "SPOOL:1\nFILAMENT:9"


def test_nfc2klipper_fits_the_smallest_chip_worth_using():
    record = klipper.from_spool(_spool(), BuildContext()).records[0]
    size = capacity.record_length(record.type, len(record.payload))
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert by_name["NTAG213"].fits
    assert by_name["NTAG212"].fits


def test_uid_only_writes_nothing_so_any_tag_will_do():
    fmt = get("uid_only")
    assert not fmt.writes_tag
    payload = fmt.build(_spool(), BuildContext())
    assert payload.records == []
    assert capacity.message_length([]) == 0
    by_name = {fit.name: fit for fit in capacity.recommend(0)}
    assert all(fit.fits for fit in by_name.values())
