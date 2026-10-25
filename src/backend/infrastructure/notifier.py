from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator


class Notifier:
    def __init__(self) -> None:
        self._waiters: dict[str, set[asyncio.Event]] = {}

    @contextlib.asynccontextmanager
    async def watch(self, job_id: str) -> AsyncIterator[asyncio.Event]:
        changed = asyncio.Event()
        self._waiters.setdefault(job_id, set()).add(changed)
        try:
            yield changed
        finally:
            waiters = self._waiters.get(job_id, set())
            waiters.discard(changed)
            if not waiters:
                self._waiters.pop(job_id, None)

    def notify(self, job_id: str) -> None:
        for changed in self._waiters.get(job_id, ()):
            changed.set()

    async def close(self) -> None:
        return None
