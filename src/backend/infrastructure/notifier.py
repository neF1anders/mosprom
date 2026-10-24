"""One LISTEN connection per process wakes every open event stream of a job."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import psycopg

from .repositories import EVENTS_CHANNEL

logger = logging.getLogger(__name__)
RECONNECT_SECONDS = 1


class PostgresNotifier:
    def __init__(self, database_url: str):
        self.conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._waiters: dict[str, set[asyncio.Event]] = {}
        self._listener: asyncio.Task[None] | None = None

    @contextlib.asynccontextmanager
    async def watch(self, job_id: str) -> AsyncIterator[asyncio.Event]:
        # Started lazily, inside the server's event loop; the worker never opens it.
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen())
        changed = asyncio.Event()
        self._waiters.setdefault(job_id, set()).add(changed)
        try:
            yield changed
        finally:
            waiters = self._waiters.get(job_id, set())
            waiters.discard(changed)
            if not waiters:
                self._waiters.pop(job_id, None)

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self.conninfo, autocommit=True
                ) as connection:
                    await connection.execute(f"LISTEN {EVENTS_CHANNEL}")
                    # Events committed while reconnecting are picked up by the next read.
                    self._wake_all()
                    async for notice in connection.notifies():
                        for changed in self._waiters.get(notice.payload, ()):
                            changed.set()
            except (psycopg.Error, OSError):
                logger.warning("Event listener lost its connection, reconnecting")
                await asyncio.sleep(RECONNECT_SECONDS)

    def _wake_all(self) -> None:
        for waiters in self._waiters.values():
            for changed in waiters:
                changed.set()

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
