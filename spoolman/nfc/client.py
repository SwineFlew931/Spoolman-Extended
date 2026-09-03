"""Client for the nfcd reader daemon.

nfcd holds no state worth persisting and answers from memory, so every call
here is short-lived and failure simply means "no reader right now". The one
exception is the event stream, which stays open for as long as the browser is
listening.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from spoolman.nfc import config

logger = logging.getLogger(__name__)


class NfcdUnavailableError(Exception):
    """The reader daemon could not be reached."""


class NfcdError(Exception):
    """The reader daemon answered, but refused the request."""

    def __init__(self, status_code: int, message: str) -> None:
        """Store the daemon's own status code and message.

        Args:
            status_code: HTTP status the daemon replied with.
            message: The daemon's explanation, passed through to the caller.

        """
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a request to nfcd and return its decoded response.

    Args:
        method: HTTP method.
        path: Path on the daemon, starting with a slash.
        payload: Optional JSON body.

    Returns:
        dict[str, Any]: The decoded response body.

    Raises:
        NfcdUnavailableError: The daemon is not running or not reachable.
        NfcdError: The daemon answered with an error status.

    """
    url = config.get_nfcd_url() + path
    try:
        async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
            response = await client.request(method, url, json=payload)
    except httpx.RequestError as exc:
        logger.debug("nfcd unreachable at %s: %s", url, exc)
        raise NfcdUnavailableError(str(exc)) from exc

    if response.is_error:
        message = _error_message(response)
        logger.warning("nfcd refused %s %s: %s", method, path, message)
        raise NfcdError(response.status_code, message)

    return response.json()


def _error_message(response: httpx.Response) -> str:
    """Pull a human-readable message out of an error response.

    Args:
        response: The failed response.

    Returns:
        str: The daemon's message, or the raw body if it is not the expected shape.

    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message")
        if isinstance(detail, str):
            return detail
    return str(body)


async def get_status() -> dict[str, Any]:
    """Get the reader's current status.

    Returns:
        dict[str, Any]: The daemon's status document.

    """
    return await request("GET", "/status")


async def stream_events() -> AsyncIterator[dict[str, Any]]:
    """Yield reader events as they happen.

    The stream ends when the daemon closes it or the consumer stops iterating.
    A daemon that goes away mid-stream ends the iteration rather than raising,
    since by then the caller has already been told the reader was present.

    Yields:
        dict[str, Any]: One decoded event per message.

    """
    url = config.get_nfcd_url() + "/events"
    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(config.REQUEST_TIMEOUT, read=None)) as client,
            client.stream("GET", url) as response,
        ):
            if response.is_error:
                await response.aread()
                raise NfcdError(response.status_code, _error_message(response))
            async for line in response.aiter_lines():
                event = _parse_sse_line(line)
                if event is not None:
                    yield event
    except httpx.RequestError as exc:
        logger.debug("nfcd event stream ended: %s", exc)
        raise NfcdUnavailableError(str(exc)) from exc


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """Decode one line of the daemon's event stream.

    Args:
        line: A raw line from the stream.

    Returns:
        dict[str, Any] | None: The event, or None for keep-alives and framing lines.

    """
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    try:
        event = json.loads(payload)
    except ValueError:
        logger.warning("Discarding unparseable event from nfcd: %.120s", payload)
        return None
    return event if isinstance(event, dict) else None


async def perform(action: str, records: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
    """Arm an operation and wait for the tag to be presented.

    The event stream is opened *before* the operation is armed, so a tag
    already resting on the reader cannot produce a result before anyone is
    listening for it.

    Waiting inside the request that armed the operation is deliberate: whatever
    has to happen on success — binding a UID, in practice — then happens in the
    same place that saw the write succeed, rather than depending on a browser
    still being connected to hear about it.

    Args:
        action: Either "write" or "erase".
        records: Records to write, empty for an erase.
        timeout: Seconds to wait for a tag before giving up.

    Returns:
        dict[str, Any]: The daemon's result event, or a synthesised timeout.

    Raises:
        NfcdUnavailableError: The daemon is not running or went away.
        NfcdError: The daemon refused the request.

    """
    request_id = uuid.uuid4().hex
    base = config.get_nfcd_url()
    body: dict[str, Any] = {"request_id": request_id}
    if action == "write":
        body["records"] = records

    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(config.REQUEST_TIMEOUT, read=None)) as client,
            client.stream("GET", base + "/events") as response,
        ):
            if response.is_error:
                await response.aread()
                raise NfcdError(response.status_code, _error_message(response))

            armed = await client.post(f"{base}/{action}", json=body)
            if armed.is_error:
                raise NfcdError(armed.status_code, _error_message(armed))

            try:
                return await asyncio.wait_for(_await_result(response, request_id), timeout)
            except TimeoutError:
                await _cancel_quietly(client, base)
                return {
                    "type": "write_failed",
                    "action": action,
                    "request_id": request_id,
                    "uid": "",
                    "message": "No tag was presented.",
                    "timed_out": True,
                }
    except httpx.RequestError as exc:
        raise NfcdUnavailableError(str(exc)) from exc


async def _await_result(response: httpx.Response, request_id: str) -> dict[str, Any]:
    """Read the stream until this operation's result comes past.

    Args:
        response: The open event stream.
        request_id: The operation to watch for.

    Returns:
        dict[str, Any]: The result event.

    Raises:
        NfcdUnavailableError: The stream ended before a result arrived.

    """
    async for line in response.aiter_lines():
        event = _parse_sse_line(line)
        if event is None or event.get("request_id") != request_id:
            continue
        if event.get("type") in {"write_ok", "write_failed"}:
            return event
    raise NfcdUnavailableError("The reader daemon closed the connection before the operation finished.")


async def _cancel_quietly(client: httpx.AsyncClient, base: str) -> None:
    """Disarm after a timeout, without letting that failure mask the timeout.

    Args:
        client: The open client.
        base: The daemon's base URL.

    """
    try:
        await client.post(base + "/cancel")
    except httpx.RequestError as exc:
        logger.debug("Could not disarm nfcd after a timeout: %s", exc)


async def await_tag(timeout: float) -> dict[str, Any]:
    """Wait for the next tag to be presented, without arming anything.

    Used by formats that write nothing and only need the tag's UID.

    Args:
        timeout: Seconds to wait before giving up.

    Returns:
        dict[str, Any]: The tag event, or a synthesised timeout result.

    Raises:
        NfcdUnavailableError: The daemon is not running or went away.
        NfcdError: The daemon refused the request.

    """
    base = config.get_nfcd_url()
    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(config.REQUEST_TIMEOUT, read=None)) as client,
            client.stream("GET", base + "/events") as response,
        ):
            if response.is_error:
                await response.aread()
                raise NfcdError(response.status_code, _error_message(response))
            try:
                return await asyncio.wait_for(_await_tag_event(response), timeout)
            except TimeoutError:
                return {"type": "write_failed", "uid": "", "message": "No tag was presented.", "timed_out": True}
    except httpx.RequestError as exc:
        raise NfcdUnavailableError(str(exc)) from exc


async def _await_tag_event(response: httpx.Response) -> dict[str, Any]:
    """Read the stream until a tag is seen.

    Args:
        response: The open event stream.

    Returns:
        dict[str, Any]: The tag event.

    Raises:
        NfcdUnavailableError: The stream ended before a tag arrived.

    """
    async for line in response.aiter_lines():
        event = _parse_sse_line(line)
        if event is not None and event.get("type") == "tag":
            return event
    raise NfcdUnavailableError("The reader daemon closed the connection before a tag was presented.")
