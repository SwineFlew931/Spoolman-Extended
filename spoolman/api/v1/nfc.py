"""NFC reader related endpoints."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from spoolman.nfc import client as nfcd
from spoolman.nfc import config

router = APIRouter(
    prefix="/nfc",
    tags=["nfc"],
)

# ruff: noqa: D103

logger = logging.getLogger(__name__)

# How long to wait before reopening a dropped connection to the daemon. Long
# enough not to hammer a daemon that is down, short enough that plugging the
# reader back in feels immediate.
RECONNECT_DELAY = 5.0

# Sent while the integration is switched off, purely so the connection is not
# idle for so long that something in the middle closes it.
DISABLED_KEEPALIVE = 30.0


class NfcStatus(BaseModel):
    """The state of the NFC reader."""

    enabled: bool = Field(description="Whether the NFC integration is switched on for this installation.")
    connected: bool = Field(description="Whether the reader daemon currently has the reader open.")
    device: str | None = Field(default=None, description="The reader device the daemon is configured to use.")
    error: str = Field(default="", description="Why the reader is unavailable, empty when it is fine.")
    transient_errors: int = Field(
        default=0,
        description="Count of recovered serial glitches since the daemon started. Expected to be non-zero.",
    )


def _disabled_status(reason: str) -> NfcStatus:
    return NfcStatus(enabled=config.is_enabled(), connected=False, error=reason)


@router.get(
    "/status",
    name="Get NFC reader status",
    description=(
        "Report whether an NFC reader is available. This never fails: a missing, disabled or wedged reader is "
        "described in the response rather than raised, so that clients can poll it unconditionally."
    ),
)
async def status() -> NfcStatus:
    if not config.is_enabled():
        return _disabled_status("NFC integration is disabled on this server.")
    try:
        raw = await nfcd.get_status()
    except nfcd.NfcdUnavailableError:
        return _disabled_status("The NFC reader daemon is not running.")
    except nfcd.NfcdError as exc:
        return _disabled_status(exc.message)
    return NfcStatus(
        enabled=True,
        connected=bool(raw.get("connected")),
        device=raw.get("device"),
        error=str(raw.get("error") or ""),
        transient_errors=int(raw.get("transient_errors") or 0),
    )


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _reader_status_event(*, connected: bool, error: str) -> dict[str, Any]:
    return {
        "type": "reader_status",
        "enabled": config.is_enabled(),
        "connected": connected,
        "error": error,
    }


async def _event_stream() -> AsyncIterator[str]:
    """Relay the daemon's events, reconnecting for as long as the client listens.

    A reader that is absent or wedged is reported as an event rather than an
    error, so the browser keeps one connection open across an unplug/replug
    instead of reconnecting in a loop of its own.

    Yields:
        str: Server-sent event frames.

    """
    if not config.is_enabled():
        yield _sse(_reader_status_event(connected=False, error="NFC integration is disabled on this server."))
        while True:
            await asyncio.sleep(DISABLED_KEEPALIVE)
            yield ": keepalive\n\n"

    while True:
        try:
            async for event in nfcd.stream_events():
                yield _sse(event)
        except nfcd.NfcdUnavailableError:
            yield _sse(_reader_status_event(connected=False, error="The NFC reader daemon is not running."))
        except nfcd.NfcdError as exc:
            yield _sse(_reader_status_event(connected=False, error=exc.message))
        else:
            # The daemon closed the stream cleanly; treat it the same as a drop.
            yield _sse(_reader_status_event(connected=False, error="The NFC reader daemon closed the connection."))
        await asyncio.sleep(RECONNECT_DELAY)


@router.get(
    "/events",
    name="Stream NFC reader events",
    description=(
        "A server-sent event stream of tag taps, write results and reader status changes. The stream stays open "
        "and reports reader availability as events, so it does not need reconnecting when the reader is unplugged."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def events() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tell nginx and friends not to buffer, which would defeat the point.
            "X-Accel-Buffering": "no",
        },
    )
