"""Fan-out of reader events from the reader thread to HTTP listeners."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from nfcd import config

logger = logging.getLogger("nfcd.events")


class EventBus:
    """Delivers events published from the reader thread to asyncio listeners.

    The reader is a plain thread, so everything it publishes has to cross onto
    the event loop before it can reach a listener. Listeners have bounded
    queues: a browser that has stopped reading is dropped events rather than
    allowed to grow the daemon's memory.
    """

    def __init__(self) -> None:
        """Create an empty bus with no loop bound yet."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self._last_status: dict[str, Any] | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the bus to the loop that will serve listeners.

        Args:
            loop: The running event loop.

        """
        self._loop = loop

    def publish_threadsafe(self, event: dict[str, Any]) -> None:
        """Publish an event from any thread.

        Dropped silently if the loop is not running yet, which only happens
        during startup and shutdown.

        Args:
            event: The event to deliver.

        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._publish, event)
        except RuntimeError:
            # The loop shut down between the check and the call.
            logger.debug("Dropping event published during shutdown: %s", event.get("type"))

    def _publish(self, event: dict[str, Any]) -> None:
        """Hand an event to every listener, dropping the oldest when one is full.

        Args:
            event: The event to deliver.

        """
        if event.get("type") == "reader_status":
            self._last_status = event
        for queue in self._listeners:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    @property
    def last_status(self) -> dict[str, Any] | None:
        """The most recent reader status event, for greeting a new listener.

        Returns:
            dict[str, Any] | None: The last status event, if there has been one.

        """
        return self._last_status

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Subscribe for as long as the context is held.

        Yields:
            asyncio.Queue[dict[str, Any]]: A queue of events for this listener.

        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=config.LISTENER_BACKLOG)
        self._listeners.add(queue)
        logger.debug("Listener attached (%d total)", len(self._listeners))
        try:
            yield queue
        finally:
            self._listeners.discard(queue)
            logger.debug("Listener detached (%d left)", len(self._listeners))


bus = EventBus()
