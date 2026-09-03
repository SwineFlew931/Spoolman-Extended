"""Capacity maths, calibrated against tags actually read with the PN532."""

from spoolman.nfc import capacity

# Measured 2026-09-03 by tapping spool 83 (OpenTag3D) and spool 105 (OpenSpool)
# on the reader. Both tags are NTAG216 clones and both reported this capacity.
MEASURED_CLONE_CAPACITY = 868

OPENTAG3D_TYPE = "application/opentag3d"
OPENSPOOL_TYPE = "application/json"


def test_record_length_matches_a_real_opentag3d_tag():
    # Spool 83 carried a 184-byte payload under a 21-character MIME type.
    assert capacity.record_length(OPENTAG3D_TYPE, 184) == 3 + 21 + 184


def test_record_length_matches_a_real_openspool_tag():
    # Spool 105 carried 251 bytes of JSON, still inside the short-record form.
    assert capacity.record_length(OPENSPOOL_TYPE, 251) == 3 + 16 + 251


def test_short_record_form_ends_at_255_bytes():
    at_limit = capacity.record_length(OPENSPOOL_TYPE, 255)
    over_limit = capacity.record_length(OPENSPOOL_TYPE, 256)
    # One more byte of payload costs four, because the length field grows.
    assert over_limit - at_limit == 4


def test_message_length_sums_records():
    records = [(OPENTAG3D_TYPE, 184), (OPENSPOOL_TYPE, 251)]
    assert capacity.message_length(records) == 208 + 270


def test_opentag3d_core_only_fits_the_smallest_usable_chip():
    # The Core block ends at 0x70, so a core-only payload is 112 bytes.
    size = capacity.record_length(OPENTAG3D_TYPE, 0x70)
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert by_name["NTAG213"].fits
    assert by_name["NTAG215"].fits
    assert by_name["NTAG216"].fits


def test_opentag3d_with_extended_block_does_not_fit_ntag213():
    # Core plus Extended runs to 0xBB, which is what a full write produces.
    size = capacity.record_length(OPENTAG3D_TYPE, 0xBB)
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert not by_name["NTAG213"].fits
    assert by_name["NTAG215"].fits


def test_openspool_with_u1_extensions_does_not_fit_ntag213():
    # This is the payload measured on spool 105.
    size = capacity.record_length(OPENSPOOL_TYPE, 251)
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert not by_name["NTAG213"].fits
    assert by_name["NTAG215"].fits
    assert by_name["NTAG216"].fits


def test_tiny_chips_are_reported_as_unsuitable_not_omitted():
    size = capacity.record_length(OPENTAG3D_TYPE, 0x70)
    names = [fit.name for fit in capacity.recommend(size)]
    assert names == ["NTAG210", "NTAG212", "NTAG213", "NTAG215", "NTAG216"]
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert not by_name["NTAG210"].fits


def test_headroom_is_reported_both_ways():
    size = capacity.record_length(OPENTAG3D_TYPE, 0x70)
    by_name = {fit.name: fit for fit in capacity.recommend(size)}
    assert by_name["NTAG216"].headroom > 0
    assert by_name["NTAG210"].headroom < 0


def test_a_real_tags_reported_capacity_beats_the_published_figure():
    # The clones report less than the 884 a genuine NTAG216 would offer, which
    # is exactly why the write-time check uses the tag's own number.
    published = next(fit for fit in capacity.recommend(0) if fit.name == "NTAG216").capacity
    assert published > MEASURED_CLONE_CAPACITY

    # Spool 105's payload fits both, but the tag's own figure is what decides.
    size = capacity.record_length(OPENSPOOL_TYPE, 251)
    assert capacity.fits(size, MEASURED_CLONE_CAPACITY)
    assert not capacity.fits(MEASURED_CLONE_CAPACITY + 1, MEASURED_CLONE_CAPACITY)


def test_a_tag_that_reports_no_capacity_is_not_refused_on_a_guess():
    assert capacity.fits(10_000, None)
    assert capacity.fits(10_000, 0)
