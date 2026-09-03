"""HTTP interface to the reader.

Only Spoolman is expected to talk to this, over loopback. There is no
authentication and no database; every answer comes from the reader thread's
in-memory state.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nfcd import config
from nfcd.events import bus
from nfcd.reader import service

# ruff: noqa: D103

logging.basicConfig(level=logging.INFO, format="%(name)-14s %(levelname)-8s %(message)s")
logger = logging.getLogger("nfcd")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run the reader for as long as the server is up.

    Args:
        _app: The application, unused.

    Yields:
        None: While the server runs.

    """
    bus.bind(asyncio.get_running_loop())
    service.start()
    logger.info("nfcd listening on %s:%d, reader %s", config.HOST, config.PORT, config.DEVICE)
    try:
        yield
    finally:
        service.stop()


app = FastAPI(
    title="nfcd",
    description="NFC reader daemon for Spoolman Extended.",
    version="1.0.0",
    lifespan=lifespan,
)


class Record(BaseModel):
    """One NDEF record, already encoded by the caller."""

    type: str = Field(description='NDEF record type, e.g. "application/opentag3d" or "urn:nfc:wkt:T".')
    name: str = Field(default="", description="Record identifier. Almost always empty.")
    data_b64: str = Field(description="Base64-encoded record payload.")


class WriteRequest(BaseModel):
    """A request to write records to the next tag presented."""

    records: list[Record] = Field(min_length=1, description="Records to write. One per tag is the norm.")
    request_id: str = Field(default="", description="Echoed back on the result event. Generated if omitted.")


class EraseRequest(BaseModel):
    """A request to blank the next tag presented."""

    request_id: str = Field(default="", description="Echoed back on the result event. Generated if omitted.")


class ArmedResponse(BaseModel):
    """Confirmation that an operation is waiting for a tag."""

    request_id: str = Field(description="Correlates with the result event on the stream.")
    armed: bool = Field(description="Always true; the result arrives as an event, not here.")


class Status(BaseModel):
    """The reader's current state."""

    device: str
    connected: bool
    error: str
    transient_errors: int
    armed: str | None = Field(default=None, description="request_id of a pending operation, if any.")
    last_tag: dict[str, Any] | None = None


@app.get("/status")
async def status() -> Status:
    pending = service.pending
    return Status(
        device=service.status["device"],
        connected=bool(service.status["connected"]),
        error=str(service.status["error"]),
        transient_errors=int(service.status["transient_errors"]),
        armed=pending["request_id"] if pending else None,
        last_tag=service.status["last_tag"],
    )


@app.post("/write")
async def write(request: WriteRequest) -> ArmedResponse:
    request_id = request.request_id or uuid.uuid4().hex
    service.arm("write", [r.model_dump() for r in request.records], request_id)
    return ArmedResponse(request_id=request_id, armed=True)


@app.post("/erase")
async def erase(request: EraseRequest) -> ArmedResponse:
    request_id = request.request_id or uuid.uuid4().hex
    service.arm("erase", [], request_id)
    return ArmedResponse(request_id=request_id, armed=True)


@app.post("/cancel")
async def cancel() -> dict[str, bool]:
    service.cancel()
    return {"cancelled": True}


async def _stream() -> AsyncIterator[str]:
    """Yield reader events, with keepalives so idle connections stay open.

    Yields:
        str: Server-sent event frames.

    """
    async with bus.listen() as queue:
        # Greet the listener with where things stand, so it does not have to
        # wait for the next change to learn whether a reader is present.
        yield _frame(
            {
                "type": "reader_status",
                "connected": bool(service.status["connected"]),
                "error": str(service.status["error"]),
            },
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=config.KEEPALIVE_INTERVAL)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _frame(event)


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
