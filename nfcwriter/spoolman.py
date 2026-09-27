"""Reading spools from Spoolman, and forwarding taps to it.

The only place this service talks to Spoolman, and it does so over the public
REST API as any other client would -- no database session, no ORM, no shared
models. That is what lets Spoolman be upgraded without touching this service.

Both calls are ones Spoolman already supports in a released version, which is
the whole point: nothing here needs a forked backend.
"""

from __future__ import annotations

import logging

import httpx

from nfcwriter import config
from nfcwriter.models import Spool

log = logging.getLogger("nfcwriter.spoolman")

# Spoolman answers a missing spool with a 404; anything else non-2xx is a fault
# on its side rather than a spool that is not there.
_NOT_FOUND = 404


class SpoolNotFoundError(LookupError):
    """Spoolman has no spool with that id."""


class SpoolmanUnreachableError(RuntimeError):
    """Spoolman did not answer."""


async def get_spool(spool_id: int) -> Spool:
    """Read one spool.

    Args:
        spool_id: The spool's id.

    Returns:
        Spool: The spool, with its filament and vendor as Spoolman nests them.

    Raises:
        SpoolNotFoundError: No such spool.
        SpoolmanUnreachableError: Spoolman did not answer, or answered with an
            error that is not a 404.

    """
    url = f"{config.SPOOLMAN_URL}/api/v1/spool/{spool_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
    except httpx.HTTPError as exc:
        msg = f"cannot reach Spoolman at {config.SPOOLMAN_URL}: {exc}"
        raise SpoolmanUnreachableError(msg) from exc

    if res.status_code == _NOT_FOUND:
        msg = f"no spool {spool_id}"
        raise SpoolNotFoundError(msg)
    if not res.is_success:
        msg = f"Spoolman returned {res.status_code} for spool {spool_id}"
        raise SpoolmanUnreachableError(msg)

    # Unknown fields are ignored by the model, so a Spoolman release that adds
    # one needs no change here.
    return Spool.model_validate(res.json())


async def forward_scan(uid: str) -> None:
    """Tell Spoolman a tag was tapped.

    Makes this service behave like any other reader when it is not writing: a
    paired browser jumps to the spool, which is Spoolman's own feature and better
    than anything this service could do about an ambient tap.

    Failures are logged and swallowed. A tap that Spoolman did not hear about is
    a missed convenience, not a reason to disturb the reader loop.

    Args:
        uid: The UID as the reader read it. Spoolman normalizes it.

    """
    if not config.FORWARD_SCANS:
        return
    url = f"{config.SPOOLMAN_URL}/api/v1/tag/scan"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(url, json={"uid": uid, "reader_id": config.READER_ID})
        if not res.is_success:
            log.debug("Spoolman answered %s to a forwarded scan", res.status_code)
    except httpx.HTTPError as exc:
        log.debug("Could not forward scan of %s: %s", uid, exc)
