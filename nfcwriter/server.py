"""HTTP interface: the whole of this service's API.

Unlike the daemon this grew out of, the browser talks to it directly. Two things
follow from that and shape the file:

  * CORS. This is a different origin from Spoolman, so every allowed origin has
    to be declared or the browser refuses the request before it is sent.
  * No database, and no authority over one. It writes tags and reports the UID it
    wrote to; linking that UID to a spool is Spoolman's job, done by the client
    through Spoolman's own API. So there is nothing here that can corrupt an
    install, which is what makes running it alongside a stock Spoolman reasonable.

`/write` and `/erase` hold the request open until the tag is dealt with. The
reader is armed and the matching result is awaited on the in-process event bus,
so the HTTP request is the operation rather than a handle to one -- a closed
connection means the user cancelled, and the reader is disarmed.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import signal
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nfcwriter import capacity, config, formats, identifiers, spoolman
from nfcwriter.events import bus
from nfcwriter.reader import service

# ruff: noqa: D103

logging.basicConfig(level=logging.INFO, format="%(name)-18s %(levelname)-8s %(message)s")
logger = logging.getLogger("nfcwriter")


# Set when the server is shutting down, so the event streams can end.
#
# Without this the service cannot be stopped cleanly, and the consequence is
# hardware-level: `/events` is an endless generator, so uvicorn waits forever for
# the connection to close, systemd gives up and sends SIGKILL, and SIGKILL skips
# the shutdown below -- leaving the reader neither released nor closed. A PN532
# left that way stops answering at all and needs its power cycled, which no
# amount of restarting fixes. Ending these streams is what makes a restart safe,
# not a tidiness measure.
_shutting_down: asyncio.Event | None = None


def _watch_for_shutdown(loop: asyncio.AbstractEventLoop) -> None:
    """End the event streams when a stop signal arrives, not when the app closes.

    The ordering here is the whole point, and getting it wrong cost a wedged
    reader. uvicorn shuts down in this order:

        1. stop accepting new connections
        2. **wait for open connections to close**
        3. run the lifespan shutdown

    `/events` is an endless stream, so step 2 waits for it forever. Setting the
    flag in the lifespan shutdown -- step 3 -- cannot work: the stream is waiting
    for a flag that is only set once the stream has closed. systemd then hits its
    stop timeout and sends SIGKILL, which skips the reader's release entirely,
    and a PN532 that is SIGKILLed answers nothing until its power is cycled.

    So the flag is set from the signal handler, which runs before any of that.
    uvicorn installs its own handlers before startup, so the existing one is
    captured and still called -- replacing it outright would stop the server
    shutting down at all.

    Args:
        loop: The running event loop, for waking the event from the handler.

    """

    def install(sig: signal.Signals) -> None:
        previous = signal.getsignal(sig)

        def handler(signum: int, frame: object, _prev: object = previous) -> None:
            if _shutting_down is not None:
                loop.call_soon_threadsafe(_shutting_down.set)
            if callable(_prev):
                _prev(signum, frame)

        signal.signal(sig, handler)

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            install(sig)
    except (ValueError, OSError):
        # Not the main thread -- under TestClient, for instance. Shutdown is then
        # only as prompt as the lifespan allows, which is fine for a test.
        logger.debug("Could not install signal handlers; shutdown may be slow")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run the reader for as long as the server is up.

    Args:
        _app: The application, unused.

    Yields:
        None: While the server runs.

    """
    global _shutting_down  # noqa: PLW0603 - one per process, created on the running loop
    _shutting_down = asyncio.Event()
    loop = asyncio.get_running_loop()
    _watch_for_shutdown(loop)
    bus.bind(loop)
    service.start()
    logger.info("nfcwriter listening on %s:%d", config.HOST, config.PORT)
    logger.info("Spoolman at %s, scan forwarding %s", config.SPOOLMAN_URL,
                "on" if config.FORWARD_SCANS else "off")
    task = asyncio.create_task(_forward_ambient_scans())
    try:
        yield
    finally:
        # Belt and braces. By the time this runs the signal handler has already
        # set it -- and it has to have, because uvicorn drains connections
        # *before* running this block. See _watch_for_shutdown.
        if _shutting_down is not None:
            _shutting_down.set()
        task.cancel()
        service.stop()


app = FastAPI(
    title="nfcwriter",
    description=(
        "Writes filament data to NFC tags for Spoolman. Reads spools over "
        "Spoolman's REST API and never writes to its database."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


async def _forward_ambient_scans() -> None:
    """Pass tags tapped outside a write on to Spoolman.

    Only taps the reader reports while nothing is armed reach here, because the
    reader consumes a tag it was armed for. So a tag being written is never also
    announced as a scan -- which is the reason this belongs in the service rather
    than being approximated by a flag in the browser.
    """
    async with bus.listen() as queue:
        while True:
            event = await queue.get()
            if event.get("type") == "tag" and event.get("uid"):
                await spoolman.forward_scan(str(event["uid"]))


class Status(BaseModel):
    connected: bool
    device: str | None
    error: str
    transient_errors: int


class FormatInfo(BaseModel):
    key: str
    label: str
    description: str
    writes_tag: bool


class PreviewRequest(BaseModel):
    spool_id: int
    format: str


class ChipInfo(BaseModel):
    name: str
    capacity: int
    fits: bool
    headroom: int


class Preview(BaseModel):
    format: str
    writes_tag: bool
    record_type: str
    size: int
    notes: list[str]
    recommended: list[ChipInfo]


class WriteRequest(BaseModel):
    spool_id: int
    format: str
    timeout: float = Field(default=60.0, gt=0, le=600)


class EraseRequest(BaseModel):
    timeout: float = Field(default=60.0, gt=0, le=600)


class OperationResult(BaseModel):
    ok: bool
    uid: str
    message: str
    written_bytes: int
    notes: list[str]


@app.get("/status")
async def status() -> Status:
    return Status(
        connected=bool(service.status["connected"]),
        device=service.status["device"],
        error=str(service.status["error"]),
        transient_errors=int(service.status["transient_errors"]),
    )


@app.get("/formats")
async def list_formats() -> list[FormatInfo]:
    return [
        FormatInfo(
            key=fmt.key,
            label=fmt.label,
            description=fmt.description,
            writes_tag=fmt.writes_tag,
        )
        for fmt in formats.all_formats()
    ]


async def _build(spool_id: int, format_key: str) -> tuple[formats.FormatDefinition, formats.TagPayload]:
    """Read a spool and render it in a format.

    Args:
        spool_id: The spool to read.
        format_key: The format to render it in.

    Returns:
        The format definition and what it produced.

    Raises:
        HTTPException: The format or spool is unknown, or Spoolman is unreachable.

    """
    try:
        definition = formats.get(format_key)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        spool = await spoolman.get_spool(spool_id)
    except spoolman.SpoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except spoolman.SpoolmanUnreachableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    context = formats.BuildContext(
        serial_id=identifiers.generate_serial(),
        online_url=f"{config.SPOOLMAN_URL}/spool/show/{spool.id}",
    )
    return definition, definition.build(spool, context)


def _size_of(payload: formats.TagPayload) -> int:
    """Measure the NDEF message a payload would occupy.

    Args:
        payload: What a format produced.

    Returns:
        Size in bytes of the bare message, which is what a tag's advertised
        capacity is measured against.

    """
    return capacity.message_length([(r.type, len(r.payload)) for r in payload.records])


@app.post("/preview")
async def preview(request: PreviewRequest) -> Preview:
    definition, payload = await _build(request.spool_id, request.format)
    size = _size_of(payload)
    return Preview(
        format=definition.key,
        writes_tag=definition.writes_tag,
        record_type=payload.records[0].type if payload.records else "",
        size=size,
        notes=payload.notes,
        recommended=[
            ChipInfo(name=chip.name, capacity=chip.capacity, fits=chip.fits, headroom=chip.headroom)
            for chip in capacity.recommend(size)
        ],
    )


async def _await_result(request_id: str, timeout: float) -> dict[str, Any]:
    """Wait for the reader to finish the operation it was armed for.

    Args:
        request_id: The id the reader echoes back on its result event.
        timeout: How long to wait for a tag.

    Returns:
        The matching `write_ok` or `write_failed` event.

    Raises:
        HTTPException: No tag was presented in time.

    """
    async with bus.listen() as queue:
        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await queue.get()
                    if (
                        event.get("type") in ("write_ok", "write_failed")
                        and event.get("request_id") == request_id
                    ):
                        return event
        except TimeoutError as exc:
            service.cancel()
            raise HTTPException(status_code=408, detail="No tag was presented.") from exc


def _result(event: dict[str, Any], notes: list[str]) -> OperationResult:
    """Turn a reader event into the API's result.

    The reader names the field `bytes`; this API calls it `written_bytes`,
    because `bytes` is a builtin and a poor field name in a public schema. That
    rename is the whole reason this function needs care: reading the wrong key
    silently yields 0, and 0 is indistinguishable from an erase -- a successful
    write then reported itself as "Tag erased." `written_bytes` is still
    accepted in case the reader is ever brought into line.

    Args:
        event: The reader's `write_ok` or `write_failed` event.
        notes: Warnings the format produced about the content.

    Returns:
        OperationResult: What to report to the caller.

    """
    written = event.get("bytes", event.get("written_bytes"))
    return OperationResult(
        ok=event.get("type") == "write_ok",
        uid=str(event.get("uid") or ""),
        message=str(event.get("message") or ""),
        written_bytes=int(written or 0),
        notes=notes,
    )


@app.post("/write")
async def write(request: WriteRequest) -> OperationResult:
    definition, payload = await _build(request.spool_id, request.format)
    size = _size_of(payload)

    records = [
        {
            "type": record.type,
            "name": record.name,
            "data_b64": base64.b64encode(record.payload).decode(),
        }
        for record in payload.records
    ]

    request_id = uuid.uuid4().hex
    # A UID-only format writes nothing, so the reader is armed to read rather
        # than write; the tag it reports is still the one to link.
    action = "write" if definition.writes_tag and records else "read"
    service.arm(action, records, request_id)
    try:
        event = await _await_result(request_id, request.timeout)
    except asyncio.CancelledError:
        # The client went away -- almost always the user pressing Cancel. Leaving
        # the reader armed would write the next tag to touch it.
        service.cancel()
        raise
    result = _result(event, payload.notes)
    if result.ok and definition.writes_tag:
        logger.info("Wrote %d bytes of %s to %s", size, definition.key, result.uid)
    return result


@app.post("/erase")
async def erase(request: EraseRequest) -> OperationResult:
    request_id = uuid.uuid4().hex
    service.arm("erase", [], request_id)
    try:
        event = await _await_result(request_id, request.timeout)
    except asyncio.CancelledError:
        service.cancel()
        raise
    return _result(event, [])


@app.post("/cancel")
async def cancel() -> dict[str, bool]:
    service.cancel()
    return {"ok": True}


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _next_frame(queue: asyncio.Queue[dict[str, Any]]) -> str:
    """Wait for one event, or give up and emit a keepalive.

    Args:
        queue: This listener's event queue.

    Returns:
        An SSE frame, a comment line when nothing arrived in time, or an empty
        string when the server is shutting down and the stream should end. The comment
        keeps proxies from closing an idle stream, and needs no handling in the
        client the way a synthetic event would.

    """
    getter = asyncio.ensure_future(queue.get())
    closing = asyncio.ensure_future(_shutting_down.wait()) if _shutting_down else None
    waits = {getter} | ({closing} if closing is not None else set())
    try:
        done, _ = await asyncio.wait(
            waits,
            timeout=config.KEEPALIVE_INTERVAL,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if getter in done:
            return _frame(getter.result())
        if closing is not None and closing in done:
            return ""
        return ": keepalive\n\n"
    finally:
        for pending in waits:
            if not pending.done():
                pending.cancel()


async def _stream() -> AsyncIterator[str]:
    """Yield reader events as SSE frames, with keepalives while idle.

    Yields:
        SSE frames.

    """
    async with bus.listen() as queue:
        last = bus.last_status
        if last is not None:
            yield _frame(last)
        while True:
            frame = await _next_frame(queue)
            if not frame:
                # Shutting down. Ending the generator lets uvicorn close this
                # connection, which is what allows the reader to be released.
                return
            yield frame


@app.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
