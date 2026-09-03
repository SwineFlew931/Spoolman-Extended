"""The generated serial, which is not the tag's UID."""

from datetime import datetime, timezone

from spoolman.nfc import identifiers

# Read off spool 105's tag, written by SpoolFlex.
REAL_SERIAL = 1788007331815877


def test_a_real_serial_decodes_to_when_the_tag_was_written():
    when = identifiers.serial_to_datetime(REAL_SERIAL)
    assert when is not None
    assert when.year == 2026
    assert when.month == 8


def test_a_serial_is_sixteen_digits_which_is_the_field_width():
    assert len(str(REAL_SERIAL)) == identifiers.SERIAL_DIGITS
    assert len(identifiers.generate_serial()) == identifiers.SERIAL_DIGITS


def test_serials_are_strictly_increasing_even_when_generated_together():
    serials = [identifiers.generate_serial() for _ in range(100)]
    assert len(set(serials)) == 100
    assert serials == sorted(serials)


def test_a_generated_serial_decodes_to_about_now():
    when = identifiers.serial_to_datetime(identifiers.generate_serial())
    assert when is not None
    assert abs((datetime.now(tz=timezone.utc) - when).total_seconds()) < 60


def test_something_that_is_not_a_serial_decodes_to_nothing():
    assert identifiers.serial_to_datetime("not-a-serial") is None
    assert identifiers.serial_to_datetime("") is None
