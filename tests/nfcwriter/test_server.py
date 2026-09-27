"""The HTTP surface, exercised end to end rather than mocked.

These exist because of a bug no unit test could have caught: `/events` read
`bus.last_status` as a method when it is a property, so every stream died on its
first frame with "'dict' object is not callable". The endpoint still imported,
still type-checked and still answered 200 -- the failure was in the response body,
after the headers had gone out. So the streaming endpoints are driven for real
here.

The reader is stubbed out. There is no PN532 on a build machine, and the real
reader thread would spend the test suite retrying a device that is not there.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nfcwriter import config, server
from nfcwriter.events import bus


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Build a client with the lifespan run, but no hardware touched."""
    monkeypatch.setattr(server.service, "start", lambda: None)
    monkeypatch.setattr(server.service, "stop", lambda: None)
    # Long enough not to race a real frame, short enough that a missing one
    # fails the test rather than hanging it.
    monkeypatch.setattr(config, "KEEPALIVE_INTERVAL", 2.0)
    with TestClient(server.app) as c:
        yield c


def test_status_reports_the_reader(client: TestClient) -> None:
    body = client.get("/status").json()
    assert set(body) == {"connected", "device", "error", "transient_errors"}


def test_formats_are_offered_in_order(client: TestClient) -> None:
    body = client.get("/formats").json()
    keys = [f["key"] for f in body]
    assert "openspool" in keys
    assert keys[0] == "opentag3d", "the default format should be offered first"
    assert next(f for f in body if f["key"] == "uid_only")["writes_tag"] is False


def test_events_streams_the_current_status_first() -> None:
    """The regression: this died on its first frame, after a 200 had been sent.

    A new listener is greeted with where things stand, so a page opening the
    stream does not have to wait for a change to learn whether a reader is there.

    Driven as an async generator rather than through TestClient, whose sync
    portal blocks on teardown waiting for an endless stream to finish -- the very
    problem `_shutting_down` exists to solve, and not one worth reproducing in a
    test just to read one frame.
    """

    async def first_frame() -> str:
        bus.bind(asyncio.get_running_loop())
        server._shutting_down = asyncio.Event()  # noqa: SLF001
        bus._publish({"type": "reader_status", "connected": True, "error": ""})  # noqa: SLF001
        agen = server._stream()  # noqa: SLF001
        try:
            return await anext(agen)
        finally:
            await agen.aclose()

    frame = asyncio.run(first_frame())
    assert frame.startswith("data: ")
    assert "reader_status" in frame


def test_events_stream_ends_when_shutting_down() -> None:
    """Why a restart is safe.

    An endless stream means uvicorn waits forever for the connection to close,
    systemd gives up and sends SIGKILL, and SIGKILL skips the shutdown that
    releases the reader. A PN532 left that way answers nothing until its power is
    cycled -- so this ending is a hardware safeguard, not tidiness.
    """

    async def drain_after_shutdown() -> list[str]:
        bus.bind(asyncio.get_running_loop())
        server._shutting_down = asyncio.Event()  # noqa: SLF001
        agen = server._stream()  # noqa: SLF001
        server._shutting_down.set()  # noqa: SLF001
        # A timeout here is a failure, not a guard: the point is that the
        # generator ends on its own.
        async with asyncio.timeout(5):
            return [frame async for frame in agen]

    frames = asyncio.run(drain_after_shutdown())
    # Terminating at all is the assertion. A greeting frame may precede the end,
    # since the bus remembers the last status; a keepalive may not, because that
    # would mean the stream waited out the interval instead of noticing.
    assert all(f.startswith("data: ") for f in frames), frames


def test_unknown_format_is_refused(client: TestClient) -> None:
    assert client.post("/preview", json={"spool_id": 1, "format": "nope"}).status_code == 400


def test_cors_allows_the_configured_origin(client: TestClient) -> None:
    """Without this header the browser refuses every call before sending it."""
    res = client.get("/status", headers={"origin": "http://spoolman.local:7912"})
    assert "access-control-allow-origin" in {k.lower() for k in res.headers}
