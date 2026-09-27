"""Finding the reader, and letting go of it properly.

A PN532 behind a CH340 bridge has no USB serial number, so the only name Linux
gives it is a kernel index -- ttyUSB0, ttyUSB1 -- and that index is not a
property of the reader. It is whichever minor was free when the driver probed.
Pinning configuration to one is what broke this daemon once already:

  * The reader was moved to a different USB port.
  * close() on the vanished device raised inside nfcpy before it reached the
    serial handle, so the old file descriptor stayed open.
  * That open descriptor kept minor 0 allocated, so the reader came back as
    ttyUSB1 -- and kept coming back as ttyUSB1 from every port thereafter.
  * Configuration still said USB0, which could now never reappear.

Neither fault alone is fatal and each hides the other: the leak makes the index
drift, and the pinned index makes the drift permanent. So this module does two
things -- resolves the reader by something that actually identifies it, on every
connection attempt rather than once at import, and guarantees the descriptor is
released when the reader goes away.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

from nfcd import config

log = logging.getLogger("nfcd.device")


class ReaderNotFoundError(RuntimeError):
    """No serial port matched, or several did and none was singled out."""


class ReaderGoneError(RuntimeError):
    """The reader was open and its device node has disappeared."""


# errno values that mean the device behind the descriptor is no longer there,
# as opposed to the framing noise this board emits while idle. ENODEV and ENXIO
# say so outright; EIO is ambiguous, so it is corroborated against the node.
_GONE_ERRNOS = frozenset({errno.ENODEV, errno.ENXIO})
_MAYBE_GONE_ERRNOS = frozenset({errno.EIO, errno.EBADF, errno.EPIPE})


def is_gone(exc: BaseException, clf: object) -> bool:
    """Decide whether an error means the reader was unplugged.

    Worth separating from ordinary errors because the two want opposite
    responses. Serial desync is ridden out by retrying on the same open
    descriptor; a removed device must be let go of at once, since holding its
    descriptor pins the kernel minor and forces the reader to come back under a
    different name.

    Args:
        exc: The exception raised by a poll.
        clf: The open nfcpy ContactlessFrontend, used to find the node path.

    Returns:
        True when the device is gone and the connection should be torn down.

    """
    err = getattr(exc, "errno", None)
    if err is None and exc.args and isinstance(exc.args[0], int):
        err = exc.args[0]  # nfcpy re-raises some IOErrors as (errno, message)

    if err in _GONE_ERRNOS:
        return True
    if err not in _MAYBE_GONE_ERRNOS:
        return False

    # EIO is this board's usual idle complaint, so only treat it as removal
    # when the node really has vanished. If the path cannot be determined,
    # assume it is the ordinary glitch and keep the existing tolerant path.
    node = _node_of(clf)
    if node is None:
        return False
    if not Path(node).exists():
        log.info("%s has disappeared; treating as a disconnect", node)
        return True
    return False


def _serial_handle(clf: object) -> object | None:
    """Reach past nfcpy to the pyserial object underneath.

    nfcpy exposes no accessor for it, and the attribute chain differs between
    driver versions, so each candidate path is walked tolerantly: a missing link
    just means there is no handle to be had.

    Args:
        clf: An nfcpy ContactlessFrontend.

    Returns:
        The pyserial Serial instance, or None.

    """
    for chain in (
        ("device", "chipset", "transport", "tty"),
        ("device", "transport", "tty"),
    ):
        probe: object | None = clf
        for attr in chain:
            probe = getattr(probe, attr, None)
            if probe is None:
                break
        if probe is not None:
            return probe
    return None


def _node_of(clf: object) -> str | None:
    """Find the device node path behind an open frontend.

    Args:
        clf: An nfcpy ContactlessFrontend.

    Returns:
        The node path, or None when it cannot be determined.

    """
    tty = _serial_handle(clf)
    port = getattr(tty, "port", None) if tty is not None else None
    return port if isinstance(port, str) else None


def _ports() -> list:
    """Enumerate serial ports.

    Returns:
        pyserial ListPortInfo objects, empty when pyserial is unavailable.

    """
    try:
        from serial.tools import list_ports  # noqa: PLC0415
    except ImportError:  # pragma: no cover - pyserial ships with nfcpy
        log.warning("pyserial unavailable; cannot discover the reader")
        return []
    return list(list_ports.comports())


def _nfcpy_path(node: str) -> str:
    """Render a device node as an nfcpy device string.

    nfcpy's tty transport matches the part between the colons against the
    basenames in /dev, so only a bare node name works here -- "/dev/ttyUSB1"
    and any /dev/serial/by-id/... symlink are both rejected by its regex.

    Args:
        node: A device node path such as /dev/ttyUSB1.

    Returns:
        An nfcpy device string such as "tty:USB1:pn532".

    """
    name = Path(node).name
    return f"tty:{name.removeprefix('tty')}:{config.DRIVER}"


def _from_path(path: str) -> str:
    """Resolve a symlink or node path the operator named explicitly.

    A /dev/serial/by-path/... link, or one made by the udev rule shipped in
    nfcd/udev/, is stable in a way the kernel index is not. It is resolved here
    rather than handed to nfcpy because nfcpy cannot parse a path.

    Args:
        path: A path to a device node or a symlink to one.

    Returns:
        An nfcpy device string.

    Raises:
        ReaderNotFoundError: The path does not exist.

    """
    real = Path(path).resolve()
    if not real.exists():
        msg = f"{path} does not exist (resolved to {real})"
        raise ReaderNotFoundError(msg)
    log.debug("Reader path %s -> %s", path, real)
    return _nfcpy_path(str(real))


def _from_location(location: str) -> str:
    """Resolve the reader by the physical USB port it is plugged into.

    This is the discriminator to use when there is more than one identical
    bridge on the bus, since CH340s carry no serial number to tell apart. It
    deliberately does change when the reader is moved: a location is a
    statement about which socket, which is exactly what a per-spool-holder
    reader needs.

    Args:
        location: A pyserial location such as "1-1.1".

    Returns:
        An nfcpy device string.

    Raises:
        ReaderNotFoundError: Nothing is plugged into that port.

    """
    for port in _ports():
        if port.location == location:
            return _nfcpy_path(port.device)
    seen = ", ".join(f"{p.device}@{p.location}" for p in _ports()) or "nothing"
    msg = f"no serial port at USB location {location} (found: {seen})"
    raise ReaderNotFoundError(msg)


def _from_usb_ids(ids: set[tuple[int, int]]) -> str:
    """Resolve the reader by USB vendor and product ID.

    The default, and correct whenever there is one reader: it follows the
    hardware across every port without configuration.

    Args:
        ids: Acceptable (vendor, product) pairs.

    Returns:
        An nfcpy device string.

    Raises:
        ReaderNotFoundError: No port matched, or several did. Several is refused
            rather than guessed, because opening the wrong bridge can drive
            an unrelated device; NFCD_USB_LOCATION resolves the ambiguity.

    """
    matches = [p for p in _ports() if (p.vid, p.pid) in ids]
    if len(matches) == 1:
        return _nfcpy_path(matches[0].device)
    wanted = ", ".join(f"{v:04x}:{p:04x}" for v, p in sorted(ids))
    if not matches:
        seen = ", ".join(f"{p.device} {p.vid:04x}:{p.pid:04x}" for p in _ports()) or "nothing"
        msg = f"no USB serial bridge matching {wanted} (found: {seen})"
        raise ReaderNotFoundError(msg)
    where = ", ".join(f"{p.device}@{p.location}" for p in matches)
    msg = (
        f"{len(matches)} bridges match {wanted} ({where}); "
        f"set NFCD_USB_LOCATION to the port the reader is in"
    )
    raise ReaderNotFoundError(msg)


def resolve() -> str:
    """Work out which nfcpy device string to open, right now.

    Called before every connection attempt, so a reader that is moved, or that
    reappears under a different kernel index, is picked up on the next retry
    without a restart.

    Returns:
        An nfcpy device string such as "tty:USB1:pn532".

    Raises:
        ReaderNotFoundError: The reader is not present.

    """
    # An explicit device string stays an escape hatch: it is the only way to
    # reach a non-USB reader, and it is what older installs already set.
    if config.DEVICE:
        log.debug("Using NFCD_DEVICE=%s verbatim", config.DEVICE)
        return config.DEVICE
    if config.DEVICE_PATH:
        return _from_path(config.DEVICE_PATH)
    if config.USB_LOCATION:
        return _from_location(config.USB_LOCATION)
    return _from_usb_ids(config.USB_IDS)


def release(clf: object) -> None:
    """Close a reader and make certain the serial descriptor is gone.

    nfcpy's close() talks to the chipset on the way out. When the device has
    already been unplugged those writes raise, and the exception escapes before
    pyserial's own close() is reached -- leaking the descriptor, which pins the
    kernel minor, which makes the index drift on reconnect. So the underlying
    handle is closed directly afterwards, and closing an already-closed
    pyserial handle is harmless.

    Args:
        clf: An nfcpy ContactlessFrontend, open or broken.

    """
    try:
        clf.close()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a broken reader cannot be shut down politely
        log.debug("nfcpy close() failed; releasing the port directly", exc_info=True)

    tty = _serial_handle(clf)
    if tty is None:
        log.debug("No serial handle found behind the frontend; nothing to release")
        return

    name = getattr(tty, "port", "?")
    try:
        if getattr(tty, "is_open", False):
            tty.close()
            log.info("Released serial handle on %s", name)
    except Exception:  # noqa: BLE001 - last resort below
        log.debug("pyserial close() on %s failed", name, exc_info=True)

    # If pyserial still will not let go, close the descriptor itself. Leaving it
    # open is the failure this whole module exists to prevent.
    try:
        if getattr(tty, "is_open", False):
            fd = tty.fileno()
            os.close(fd)
            log.warning("Force-closed fd %d on %s", fd, name)
    except Exception:  # noqa: BLE001 - nothing further can be done
        log.debug("Could not force-close %s", name, exc_info=True)
