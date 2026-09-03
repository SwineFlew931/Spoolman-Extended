"""NFC reader related endpoints."""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.api.v1 import models
from spoolman.api.v1.models import Message
from spoolman.database import setting as setting_db
from spoolman.database import spool as spool_db
from spoolman.database.database import get_db_session
from spoolman.exceptions import ItemNotFoundError
from spoolman.nfc import binding, capacity, config, formats, identifiers
from spoolman.nfc import client as nfcd
from spoolman.nfc.binding import UidAlreadyBoundError
from spoolman.nfc.formats import BuildContext, FormatDefinition, TagPayload
from spoolman.settings import parse_setting

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


class TagFormatInfo(BaseModel):
    """A tag format the write dialog can offer."""

    key: str = Field(description="Identifier used when asking for a write.")
    label: str = Field(description="Name to show in the dropdown.")
    description: str = Field(description="What this format is good for, and what it costs.")
    writes_tag: bool = Field(description="False for formats that only bind the tag's UID.")


class ChipRecommendation(BaseModel):
    """Whether one NTAG variant can hold a particular payload."""

    name: str
    capacity: int = Field(description="Largest NDEF message this chip is expected to hold, in bytes.")
    fits: bool
    headroom: int = Field(description="Bytes to spare, negative when the payload is too large.")


class PreviewRequest(BaseModel):
    """Ask what a format would write for a spool."""

    spool_id: int
    format: str


class PreviewResponse(BaseModel):
    """What would be written, and what tag would hold it."""

    format: str
    writes_tag: bool
    record_type: str = Field(default="", description="NDEF type of the record, empty when nothing is written.")
    size: int = Field(description="Encoded NDEF message length in bytes.")
    notes: list[str] = Field(default_factory=list, description="Content that had to give, in the user's terms.")
    recommended: list[ChipRecommendation] = Field(description="Every known chip, smallest first.")


class WriteRequest(BaseModel):
    """Write a spool to the next tag presented."""

    spool_id: int
    format: str
    bind: bool = Field(default=True, description="Add the tag's UID to the spool once the write succeeds.")
    timeout: float = Field(default=60.0, gt=0, le=600, description="Seconds to wait for a tag.")


class OperationResponse(BaseModel):
    """The outcome of a write or an erase."""

    ok: bool
    uid: str = Field(default="", description="UID of the tag that was used.")
    message: str = Field(default="", description="Why it failed, empty on success.")
    written_bytes: int = Field(default=0)
    bound: bool = Field(default=False, description="Whether the UID was added to a spool.")
    unbound_from: int | None = Field(default=None, description="Spool the UID was removed from, if any.")
    notes: list[str] = Field(default_factory=list)


class EraseRequest(BaseModel):
    """Blank the next tag presented."""

    unbind: bool = Field(default=True, description="Also remove the tag's UID from whatever spool holds it.")
    timeout: float = Field(default=60.0, gt=0, le=600, description="Seconds to wait for a tag.")


class UidOwnerResponse(BaseModel):
    """Which spool a UID belongs to."""

    uid: str
    free: bool
    spool_id: int | None = None
    spool_name: str = ""
    archived: bool = False


def _require_enabled() -> None:
    if not config.is_enabled():
        raise HTTPException(status_code=503, detail="The NFC integration is disabled on this server.")


async def _online_url(db: AsyncSession, spool_id: int) -> str:
    """Build the short URL to put on a tag, if this instance has an address.

    The field is 32 bytes, so the short /s/{id} route is used. When no base URL
    is configured nothing is written, which is the right default: a URL nobody
    can resolve is worse than no URL.

    Args:
        db: The database session.
        spool_id: The spool to link to.

    Returns:
        str: The URL, or an empty string.

    """
    try:
        stored = await setting_db.get(db, parse_setting("base_url"))
    except ItemNotFoundError:
        return ""
    base = str(json.loads(stored.value) or "").rstrip("/")
    return f"{base}/s/{spool_id}" if base else ""


async def _build(db: AsyncSession, spool_id: int, format_key: str) -> tuple[FormatDefinition, TagPayload]:
    """Load a spool and render it in the requested format.

    Args:
        db: The database session.
        spool_id: The spool to render.
        format_key: Which format to use.

    Returns:
        tuple[FormatDefinition, TagPayload]: The format and what it produced.

    Raises:
        HTTPException: No such format.

    """
    try:
        definition = formats.get(format_key)
    except KeyError as exc:
        # str() on a KeyError re-quotes its argument, which would reach the user
        # as an oddly double-quoted message.
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc

    db_spool = await spool_db.get_by_id(db, spool_id)
    spool = models.Spool.from_db(db_spool)
    context = BuildContext(
        serial_id=identifiers.generate_serial(),
        online_url=await _online_url(db, spool_id),
    )
    return definition, definition.build(spool, context)


def _message_size(payload: TagPayload) -> int:
    return capacity.message_length([(record.type, len(record.payload)) for record in payload.records])


@router.get("/formats", name="List tag formats")
async def list_formats() -> list[TagFormatInfo]:
    return [
        TagFormatInfo(key=fmt.key, label=fmt.label, description=fmt.description, writes_tag=fmt.writes_tag)
        for fmt in formats.all_formats()
    ]


@router.post(
    "/preview",
    name="Preview a tag write",
    description=(
        "Render a spool in a tag format without writing anything, and report which NTAG chips would hold it. "
        "The recommendation is computed from this spool's actual payload, so it changes with the spool and the "
        "format. It is advisory: the tag's own reported capacity is what decides at write time."
    ),
)
async def preview(request: PreviewRequest, db: Annotated[AsyncSession, Depends(get_db_session)]) -> PreviewResponse:
    definition, payload = await _build(db, request.spool_id, request.format)
    size = _message_size(payload)
    return PreviewResponse(
        format=definition.key,
        writes_tag=definition.writes_tag,
        record_type=payload.records[0].type if payload.records else "",
        size=size,
        notes=payload.notes,
        recommended=[
            ChipRecommendation(name=fit.name, capacity=fit.capacity, fits=fit.fits, headroom=fit.headroom)
            for fit in capacity.recommend(size)
        ],
    )


@router.post(
    "/write",
    name="Write a tag",
    description=(
        "Arm the reader and wait for a tag to be presented, then write the spool to it, verify by reading it "
        "back, and bind the tag's UID to the spool. Returns when the tag has been dealt with or the wait times "
        "out. A UID already held by a different spool is refused with 409 after the write, since the UID is not "
        "knowable until the tag is in front of the reader."
    ),
    responses={409: {"model": Message}, 503: {"model": Message}},
)
async def write(request: WriteRequest, db: Annotated[AsyncSession, Depends(get_db_session)]) -> OperationResponse:
    _require_enabled()
    definition, payload = await _build(db, request.spool_id, request.format)

    try:
        if definition.writes_tag:
            records = [
                {"type": record.type, "name": record.name, "data_b64": base64.b64encode(record.payload).decode()}
                for record in payload.records
            ]
            result = await nfcd.perform("write", records, request.timeout)
        else:
            # Nothing to write; this format is the UID binding and nothing else.
            result = await nfcd.await_tag(request.timeout)
    except nfcd.NfcdUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"The NFC reader is not available: {exc}") from exc
    except nfcd.NfcdError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc

    if result.get("type") == "write_failed":
        return OperationResponse(ok=False, uid=result.get("uid", ""), message=result.get("message", ""))

    uid = str(result.get("uid", ""))
    response = OperationResponse(
        ok=True,
        uid=uid,
        written_bytes=int(result.get("bytes") or 0),
        notes=payload.notes,
    )
    if not request.bind or not uid:
        return response

    try:
        await binding.bind(db, request.spool_id, uid)
    except UidAlreadyBoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.bound = True
    return response


@router.post(
    "/erase",
    name="Erase a tag",
    description=(
        "Blank the next tag presented, leaving it formatted and reusable, and optionally remove its UID from "
        "whatever spool holds it."
    ),
    responses={503: {"model": Message}},
)
async def erase(request: EraseRequest, db: Annotated[AsyncSession, Depends(get_db_session)]) -> OperationResponse:
    _require_enabled()
    try:
        result = await nfcd.perform("erase", [], request.timeout)
    except nfcd.NfcdUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"The NFC reader is not available: {exc}") from exc
    except nfcd.NfcdError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc

    if result.get("type") == "write_failed":
        return OperationResponse(ok=False, uid=result.get("uid", ""), message=result.get("message", ""))

    uid = str(result.get("uid", ""))
    response = OperationResponse(ok=True, uid=uid)
    if request.unbind and uid:
        owner = await binding.find_owner(db, uid)
        if owner.spool_id is not None:
            await binding.unbind(db, owner.spool_id, uid)
            response.unbound_from = owner.spool_id
    return response


@router.get(
    "/uid/{uid}",
    name="Look up a tag UID",
    description=(
        "Report which spool holds a UID, archived spools included. The usable UID space on these tags is small "
        "enough that collisions are expected, so this is checked before every bind."
    ),
)
async def uid_owner(uid: str, db: Annotated[AsyncSession, Depends(get_db_session)]) -> UidOwnerResponse:
    owner = await binding.find_owner(db, uid)
    return UidOwnerResponse(
        uid=owner.uid,
        free=owner.is_free,
        spool_id=owner.spool_id,
        spool_name=owner.spool_name,
        archived=owner.archived,
    )


@router.delete(
    "/spool/{spool_id}/uid/{uid}",
    name="Unbind a tag from a spool",
    description="Remove one UID from a spool, leaving any others it holds alone. The tag itself is not touched.",
)
async def unbind(spool_id: int, uid: str, db: Annotated[AsyncSession, Depends(get_db_session)]) -> list[str]:
    return await binding.unbind(db, spool_id, uid)
