"""Client for the nfcd reader daemon.

nfcd holds no state worth persisting and answers from memory, so every call
here is short-lived and failure simply means "no reader right now". The one
exception is the event stream, which stays open for as long as the browser is
listening.
"""

import json
import logging
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
