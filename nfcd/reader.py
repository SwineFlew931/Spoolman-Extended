"""The PN532 reader thread.

Everything in here is shaped by three measured properties of this particular
board (an AITRIP PN532 V3 behind a CH340 bridge). They are documented at the
point they are handled rather than in one list, because each one looks like a
bug until you know why the code is written that way.
"""

import base64
import logging
import threading
import time
from typing import Any

from nfcd import config
from nfcd.events import bus

log = logging.getLogger("nfcd.reader")

# Transient framing errors are expected on this board and are recovered from, so
# our own status reporting speaks for reader health instead of nfcpy's noise.
for _noisy in ("nfc.clf", "nfc.clf.pn532", "nfc.tag"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

# RFConfiguration item 0x05 = MaxRetries {ATR, PSL, PassiveActivation}. One
# passive-activation attempt makes a poll return promptly when no tag is there,
# instead of the chip retrying until it times out.
RF_CONFIG_MAX_RETRIES = 0x05
RF_CONFIG_RETRY_VALUES = b"\xff\x01\x01"


class ReaderService:
    """Owns the reader hardware and the thread that polls it."""

    def __init__(self) -> None:
        """Create a stopped service."""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, Any] | None = None
        self._last_uid: str = ""
        self._last_seen: float = 0.0
        self._transient = 0
        self.status: dict[str, Any] = {
            "device": config.DEVICE,
            "connected": False,
            "error": "",
            "last_tag": None,
            "transient_errors": 0,
        }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start polling, if not already running."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="nfc-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop polling and wait briefly for the thread to notice."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # -- write queue ------------------------------------------------------

    def arm(self, action: str, records: list[dict[str, Any]], request_id: str) -> None:
        """Arm an operation for the next tag presented.

        Clears the retap suppression as well: the tag is usually still resting
        on the reader from the read that prompted this, and waiting out the
        grace period would look like the write had been ignored.

        Args:
            action: Either "write" or "erase".
            records: Records to write, empty for an erase.
            request_id: Caller's id, echoed back on the result event.

        """
        with self._lock:
            self._pending = {"action": action, "records": records, "request_id": request_id}
            self._last_uid = ""
        bus.publish_threadsafe({"type": "armed", "action": action, "request_id": request_id})

    def cancel(self) -> None:
        """Disarm any pending operation."""
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            bus.publish_threadsafe({"type": "cancelled", "request_id": pending["request_id"]})

    @property
    def pending(self) -> dict[str, Any] | None:
        """The operation waiting for a tag, if any.

        Returns:
            dict[str, Any] | None: A copy of the pending operation.

        """
        with self._lock:
            return dict(self._pending) if self._pending else None

    # -- reader thread ----------------------------------------------------

    def _run(self) -> None:
        """Keep a reader open, reconnecting whenever it goes away."""
        try:
            import nfc  # noqa: PLC0415
        except ImportError as exc:
            self._set_status(connected=False, error=f"nfcpy unavailable: {exc}")
            log.exception("nfcpy import failed")
            return

        while not self._stop.is_set():
            clf = None
            try:
                import nfc  # noqa: PLC0415

                clf = nfc.ContactlessFrontend(config.DEVICE)
                _suppress_power_down(clf)
                _shorten_activation_retries(clf)
                self._set_status(connected=True, error="")
                log.info("PN532 open on %s", config.DEVICE)
                self._poll_loop(clf)
            except Exception as exc:  # noqa: BLE001 - any failure here means "no reader", and we retry
                self._set_status(connected=False, error=str(exc))
                log.warning("Reader unavailable (%s); retrying in %.0fs", exc, config.RECONNECT_WAIT)
                self._stop.wait(config.RECONNECT_WAIT)
            finally:
                if clf is not None:
                    try:
                        clf.close()
                    except Exception:  # noqa: BLE001 - closing a broken reader is best-effort
                        log.debug("Ignoring error while closing the reader")
        self._set_status(connected=False, error="Reader stopped.")

    def _poll_loop(self, clf: Any) -> None:  # noqa: ANN401 - nfcpy is an optional import
        """Sense, activate, handle; tolerant of this board's framing glitches.

        The PN532 sits behind a CH340 bridge and intermittently produces "frame
        length value mismatch", "frame data checksum error" or [Errno 5] while
        idle. That is serial desync, not a dead reader. Treating each one as
        fatal tore the connection down every few seconds, so transient failures
        are counted and only a sustained run of them forces a reconnect.

        clf.sense() is used rather than clf.connect() because connect()'s
        terminate/abort path is what provokes them in the first place.

        Args:
            clf: An open nfcpy ContactlessFrontend.

        Raises:
            RuntimeError: The reader produced too many consecutive errors.

        """
        import nfc  # noqa: PLC0415
        from nfc.clf import RemoteTarget  # noqa: PLC0415

        consecutive = 0
        while not self._stop.is_set():
            try:
                target = clf.sense(RemoteTarget("106A"), iterations=1, interval=0.2)
                consecutive = 0
            except Exception as exc:  # see docstring: these are serial desync, not a dead reader
                consecutive += 1
                self._transient += 1
                self.status["transient_errors"] = self._transient
                log.debug("Transient sense error %d/%d: %s", consecutive, config.MAX_CONSECUTIVE_ERRORS, exc)
                if consecutive >= config.MAX_CONSECUTIVE_ERRORS:
                    raise RuntimeError(f"reader unresponsive after {consecutive} consecutive errors: {exc}") from exc
                self._stop.wait(config.POLL_IDLE)
                continue

            if target is None:
                self._stop.wait(config.POLL_IDLE)
                continue

            try:
                tag = nfc.tag.activate(clf, target)
            except Exception as exc:  # noqa: BLE001 - a tag pulled away mid-activation is routine
                log.debug("Activation failed: %s", exc)
                self._stop.wait(config.POLL_IDLE)
                continue

            if tag is None or not hasattr(tag, "identifier"):
                self._stop.wait(config.POLL_IDLE)
                continue

            try:
                self._handle(tag)
            except Exception as exc:  # one bad tag must not end the loop
                log.exception("Tag handling failed")
                bus.publish_threadsafe({"type": "error", "message": str(exc)})

    def _handle(self, tag: Any) -> None:  # noqa: ANN401 - nfcpy is an optional import
        """Act on one activated tag: perform a pending operation, or report it.

        Args:
            tag: The activated nfcpy tag.

        """
        uid = "".join(f"{b:02X}" for b in bytes(tag.identifier))
        now = time.time()

        with self._lock:
            pending, self._pending = self._pending, None
            if pending is None and uid == self._last_uid and (now - self._last_seen) < config.RETAP_GRACE:
                return
            self._last_uid, self._last_seen = uid, now

        if pending is not None:
            self._perform(tag, uid, pending)
            return

        event = {"type": "tag", "uid": uid, **_read_tag(tag)}
        self.status["last_tag"] = event
        bus.publish_threadsafe(event)

    def _perform(self, tag: Any, uid: str, pending: dict[str, Any]) -> None:  # noqa: ANN401
        """Carry out an armed write or erase and report the outcome.

        Args:
            tag: The activated nfcpy tag.
            uid: The tag's UID, uppercase hex.
            pending: The armed operation.

        """
        request_id = pending["request_id"]
        try:
            import ndef  # noqa: PLC0415
        except ImportError as exc:
            self._fail(request_id, uid, f"ndeflib unavailable: {exc}")
            return

        try:
            records = [
                ndef.Record(r["type"], r.get("name", ""), base64.b64decode(r["data_b64"])) for r in pending["records"]
            ] or [ndef.Record()]
            _prepare_for_write(tag)
            encoded = b"".join(ndef.message_encoder(records))
            capacity = int(getattr(tag.ndef, "capacity", 0) or 0)
            if capacity and len(encoded) > capacity:
                raise RuntimeError(  # noqa: TRY301
                    f"payload is {len(encoded)} bytes but this tag holds {capacity}",
                )
            tag.ndef.records = records
            _verify(tag, records)
        except Exception as exc:  # noqa: BLE001 - every failure here is reported, not raised
            log.warning("%s on %s failed: %s", pending["action"], uid, exc)
            self._fail(request_id, uid, str(exc))
            return

        log.info("%s on %s succeeded (%d bytes)", pending["action"], uid, len(encoded))
        bus.publish_threadsafe(
            {
                "type": "write_ok",
                "action": pending["action"],
                "request_id": request_id,
                "uid": uid,
                "bytes": len(encoded),
                **_read_tag(tag),
            },
        )

    def _fail(self, request_id: str, uid: str, message: str) -> None:
        """Report a failed operation.

        Args:
            request_id: The caller's id for the operation.
            uid: The tag's UID.
            message: What went wrong, in terms a user can act on.

        """
        bus.publish_threadsafe(
            {"type": "write_failed", "request_id": request_id, "uid": uid, "message": message},
        )

    def _set_status(self, *, connected: bool, error: str) -> None:
        """Update and announce reader status.

        Args:
            connected: Whether the reader is open.
            error: Why it is not, empty when it is.

        """
        self.status.update(connected=connected, error=error)
        bus.publish_threadsafe({"type": "reader_status", "connected": connected, "error": error})


def _read_tag(tag: Any) -> dict[str, Any]:  # noqa: ANN401 - nfcpy is an optional import
    """Describe a tag's NDEF content without interpreting it.

    Formats are Spoolman's business, so records come back as raw bytes. What
    the daemon does contribute is the tag's own reported capacity, which is the
    only trustworthy answer to "will this fit" — the clones in use here
    advertise 872 bytes in their capability container but hold 888.

    Args:
        tag: The activated nfcpy tag.

    Returns:
        dict[str, Any]: Capacity, writability and the records found.

    """
    out: dict[str, Any] = {"records": [], "blank": True, "capacity": None, "writeable": None}
    try:
        ndef_obj = tag.ndef
    except Exception as exc:  # noqa: BLE001 - an unformatted or half-read tag is not an error
        return {**out, "error": f"NDEF read failed: {exc}"}
    if ndef_obj is None:
        return out

    out["capacity"] = int(getattr(ndef_obj, "capacity", 0) or 0) or None
    out["writeable"] = bool(getattr(ndef_obj, "is_writeable", False))
    records = list(getattr(ndef_obj, "records", []))
    out["blank"] = not any(bytes(getattr(rec, "data", b"") or b"") for rec in records)
    for rec in records:
        data = bytes(getattr(rec, "data", b"") or b"")
        out["records"].append(
            {
                "type": getattr(rec, "type", "") or "",
                "name": getattr(rec, "name", "") or "",
                "length": len(data),
                "data_b64": base64.b64encode(data).decode("ascii"),
            },
        )
    return out


def _prepare_for_write(tag: Any) -> None:  # noqa: ANN401 - nfcpy is an optional import
    """Make sure a tag is NDEF-formatted and writable.

    Args:
        tag: The activated nfcpy tag.

    Raises:
        RuntimeError: The tag cannot be written.

    """
    if tag.ndef is None:
        formatter = getattr(tag, "format", None)
        if formatter is None or not formatter():
            raise RuntimeError("tag is not NDEF-formatted and could not be formatted")
    if not tag.ndef.is_writeable:
        raise RuntimeError("tag is write-protected")


def _verify(tag: Any, expected: list[Any]) -> None:  # noqa: ANN401 - nfcpy is an optional import
    """Re-read the tag and confirm it holds what was just written.

    Args:
        tag: The activated nfcpy tag.
        expected: The records that were written.

    Raises:
        RuntimeError: The tag does not match what was written.

    """
    written = list(getattr(tag.ndef, "records", []))
    if len(written) != len(expected):
        raise RuntimeError(f"verification failed: tag holds {len(written)} records, expected {len(expected)}")
    for got, want in zip(written, expected, strict=True):
        if bytes(got.data or b"") != bytes(want.data or b"") or got.type != want.type:
            raise RuntimeError("verification failed: tag content does not match what was written")


def _suppress_power_down(clf: Any) -> None:  # noqa: ANN401 - nfcpy is an optional import
    """Stop nfcpy putting this board to sleep on close().

    nfc/clf/pn532.py Device.close() calls power_down(wakeup_enable=("I2C",
    "SPI", "HSU")) with a 100 ms timeout. On this CH340-bridged board the link
    intermittently garbles frames, and a corrupted PowerDown lands the chip in
    sleep WITHOUT the HSU wakeup source set — after which it ignores all serial
    traffic and only a physical unplug/replug revives it. A USB reset is not
    enough; that cycles the bridge, not the PN532 behind it.

    Closing the transport without the PowerDown command loses nothing: the chip
    idles at a few mA either way.

    Args:
        clf: An open nfcpy ContactlessFrontend.

    """
    try:
        chipset = clf.device.chipset
    except AttributeError:
        return
    if hasattr(chipset, "power_down"):
        chipset.power_down = lambda *_args, **_kwargs: None
        log.info("power_down suppressed (prevents the PN532 wedging on close)")


def _shorten_activation_retries(clf: Any) -> None:  # noqa: ANN401 - nfcpy is an optional import
    """Ask the chip to give up quickly when no tag is present.

    Without this the chip retries passive activation until it times out, and a
    poll against empty air takes long enough to make the reader feel laggy.

    Args:
        clf: An open nfcpy ContactlessFrontend.

    """
    try:
        clf.device.chipset.rf_configuration(RF_CONFIG_MAX_RETRIES, RF_CONFIG_RETRY_VALUES)
    except Exception as exc:  # noqa: BLE001 - a chipset that will not take this still works
        log.debug("Could not shorten activation retries: %s", exc)


service = ReaderService()
