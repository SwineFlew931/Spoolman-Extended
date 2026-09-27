"""Tests for reader discovery and descriptor release."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from nfcwriter import config, device


class FakePort(SimpleNamespace):
    pass


def _port(
    dev: str,
    vid: int = 0x1A86,
    pid: int = 0x7523,
    location: str = "1-1.1",
) -> FakePort:
    return FakePort(device=dev, vid=vid, pid=pid, location=location, serial_number=None)


@pytest.fixture(autouse=True)
def _no_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DEVICE", "")
    monkeypatch.setattr(config, "DEVICE_PATH", "")
    monkeypatch.setattr(config, "USB_LOCATION", "")
    monkeypatch.setattr(config, "USB_IDS", {(0x1A86, 0x7523)})


def test_finds_reader_at_any_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression: a reader that came back as ttyUSB1 must still be found."""
    monkeypatch.setattr(device, "_ports", lambda: [_port("/dev/ttyUSB1")])
    assert device.resolve() == "tty:USB1:pn532"


def test_explicit_device_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DEVICE", "tty:S0:pn532")
    monkeypatch.setattr(device, "_ports", list)
    assert device.resolve() == "tty:S0:pn532"


def test_missing_reader_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "_ports", list)
    with pytest.raises(device.ReaderNotFoundError):
        device.resolve()


def test_ambiguous_readers_refuse_to_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        device,
        "_ports",
        lambda: [_port("/dev/ttyUSB0", location="1-1.1"), _port("/dev/ttyUSB1", location="1-1.2")],
    )
    with pytest.raises(device.ReaderNotFoundError, match="NFCD_USB_LOCATION"):
        device.resolve()


def test_location_disambiguates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "USB_LOCATION", "1-1.2")
    monkeypatch.setattr(
        device,
        "_ports",
        lambda: [_port("/dev/ttyUSB0", location="1-1.1"), _port("/dev/ttyUSB1", location="1-1.2")],
    )
    assert device.resolve() == "tty:USB1:pn532"


def test_symlink_path_is_resolved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    node = tmp_path / "ttyUSB7"
    node.touch()
    link = tmp_path / "nfc-reader"
    link.symlink_to(node)
    monkeypatch.setattr(config, "DEVICE_PATH", str(link))
    assert device.resolve() == "tty:USB7:pn532"


def test_release_closes_handle_when_nfcpy_close_raises() -> None:
    """The leak: nfcpy's close() raises on a vanished device, so we close it."""
    closed = []

    class Tty:
        port = "/dev/ttyUSB0"
        is_open = True

        def close(self) -> None:
            closed.append(True)
            Tty.is_open = False

    class Clf:
        device = SimpleNamespace(chipset=SimpleNamespace(transport=SimpleNamespace(tty=Tty())))

        def close(self) -> None:
            raise OSError(19, "No such device")

    device.release(Clf())
    assert closed == [True], "serial handle must be closed even when nfcpy close() fails"


def test_release_tolerates_a_frontend_with_no_handle() -> None:
    class Clf:
        def close(self) -> None:
            pass

    device.release(Clf())  # must not raise


def _clf_on(node: str) -> object:
    class Tty:
        port = node
        is_open = True

        def close(self) -> None:
            Tty.is_open = False

    class Clf:
        device = SimpleNamespace(chipset=SimpleNamespace(transport=SimpleNamespace(tty=Tty())))

        def close(self) -> None:
            pass

    return Clf()


def test_enodev_is_a_disconnect(tmp_path: Path) -> None:
    node = tmp_path / "ttyUSB0"
    node.touch()
    exc = OSError(19, "No such device")
    assert device.is_gone(exc, _clf_on(str(node))) is True


def test_nfcpy_tuple_style_errno_is_understood(tmp_path: Path) -> None:
    """Nfcpy re-raises some IOErrors as a bare (errno, message) tuple."""
    exc = Exception((19, "No such device"))
    exc.args = (19, "No such device")
    assert device.is_gone(exc, _clf_on(str(tmp_path / "gone"))) is True


def test_eio_with_node_present_is_just_noise(tmp_path: Path) -> None:
    """The board emits EIO while idle; that must stay a tolerated glitch."""
    node = tmp_path / "ttyUSB0"
    node.touch()
    exc = OSError(5, "Input/output error")
    assert device.is_gone(exc, _clf_on(str(node))) is False


def test_eio_with_node_vanished_is_a_disconnect(tmp_path: Path) -> None:
    exc = OSError(5, "Input/output error")
    assert device.is_gone(exc, _clf_on(str(tmp_path / "ttyUSB0"))) is True


def test_framing_error_is_not_a_disconnect(tmp_path: Path) -> None:
    node = tmp_path / "ttyUSB0"
    node.touch()
    exc = Exception("frame length value mismatch")
    assert device.is_gone(exc, _clf_on(str(node))) is False
