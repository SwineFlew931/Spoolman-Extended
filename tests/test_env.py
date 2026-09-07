"""Tests for environment variable parsing."""

import pytest

from spoolman import env


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://spoolman.local", "https://spoolman.local"),
        ("  https://spoolman.local  ", "https://spoolman.local"),
        ("https://spoolman.local/", "https://spoolman.local"),
        ("https://spoolman.local///", "https://spoolman.local"),
        ("HTTPS://Spoolman.Local", "https://spoolman.local"),
        ("*", "*"),
    ],
)
def test_normalize_origin(raw: str, expected: str):
    assert env.normalize_origin(raw) == expected


def test_get_cors_origin_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPOOLMAN_CORS_ORIGIN", raising=False)
    assert env.get_cors_origin() is None
    assert env.is_cors_defined() is False


def test_get_cors_origin_single(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_CORS_ORIGIN", "https://spoolman.local")
    assert env.get_cors_origin() == ["https://spoolman.local"]
    assert env.is_cors_defined() is True


def test_get_cors_origin_trims_list_entries(monkeypatch: pytest.MonkeyPatch):
    """A space after the comma must not produce an entry no Origin header can ever match."""
    monkeypatch.setenv("SPOOLMAN_CORS_ORIGIN", "https://a.local, https://b.local/")
    assert env.get_cors_origin() == ["https://a.local", "https://b.local"]


def test_get_cors_origin_drops_empty_and_duplicate_entries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_CORS_ORIGIN", "https://a.local,,https://a.local/, ")
    assert env.get_cors_origin() == ["https://a.local"]


def test_get_cors_origin_raw_is_unparsed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPOOLMAN_CORS_ORIGIN", " https://a.local, https://b.local ")
    assert env.get_cors_origin_raw() == " https://a.local, https://b.local "


@pytest.mark.parametrize(
    ("declared", "reported", "fork"),
    [
        # This fork. Moonraker, Happy Hare and SpoolLink compare the reported
        # version against Spoolman releases they know about, so it has to be one.
        ("0.26.1+ext.1", "0.26.1", "0.26.1+ext.1"),
        ("0.26.1+ext.12", "0.26.1", "0.26.1+ext.12"),
        ("0.27.0+ext.1", "0.27.0", "0.27.0+ext.1"),
        # A plain upstream build reports itself unchanged and claims no fork.
        ("0.26.1", "0.26.1", None),
        ("unknown", "unknown", None),
    ],
)
def test_version_splits_off_the_local_segment(
    monkeypatch: pytest.MonkeyPatch,
    declared: str,
    reported: str,
    fork: str | None,
):
    monkeypatch.setattr(env, "_read_declared_version", lambda: declared)
    assert env.get_version() == reported
    assert env.get_fork_version() == fork


def test_reported_version_never_carries_a_local_segment(monkeypatch: pytest.MonkeyPatch):
    # The whole point: whatever is declared, what integrations read is a version
    # upstream has actually released.
    monkeypatch.setattr(env, "_read_declared_version", lambda: "0.26.1+ext.99")
    assert "+" not in env.get_version()
