"""Stage work is a row written on the caller's transaction, so state and work commit together.

One process serves the API and runs the stages: the runner claims the rows, a job at a time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import tables as t

logger = logging.getLogger(__name__)

STAGE1_TASK = "stage1.run"
# Parameter selection and its check run as this task; its payload is {job_id, revision}.
STAGE2_TASK = "stage2.select_parameters"
TODO, DOING, DONE, FAILED, CANCELLED = "todo", "doing", "done", "failed", "cancelled"


class SqlQueue:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def stage1(self, job_id: str, revision: int, start: bool = False) -> None:
        await self._add(STAGE1_TASK, job_id, revision, start)

    async def stage2(self, job_id: str, revision: int) -> None:
        await self._add(STAGE2_TASK, job_id, revision, False)

    async def cancel_pending(self, job_id: str) -> None:
        """Work queued for an earlier revision is obsolete."""
        await self._session.execute(
            update(t.task_queue)
            .where(t.task_queue.c.job_id == job_id, t.task_queue.c.status == TODO)
            .values(status=CANCELLED)
        )

    async def _add(self, task: str, job_id: str, revision: int, start: bool) -> None:
        await self._session.execute(
            t.task_queue.insert().values(
                task=task, job_id=job_id, revision=revision, start=start, status=TODO
            )
        )
        self._session.info["wake"] = True


Handler = Callable[[str, int, bool], Awaitable[None]]


class TaskRunner:
    """Runs queued work: at most ``concurrency`` jobs at a time, one task per job at a time."""

    def __init__(self, uow, wake: asyncio.Event, handlers: dict[str, Handler], concurrency: int):
        self._uow, self._wake, self._handlers = uow, wake, handlers
        self._concurrency = concurrency
        self._running: dict[str, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        # Work a stopped process left half done runs again; the handlers are idempotent.
        async with self._uow() as uow:
            await uow._session.execute(
                update(t.task_queue)
                .where(t.task_queue.c.status == DOING)
                .values(status=TODO)
            )
            await uow.commit()
        self._wake.set()
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        for running in list(self._running.values()):
            running.cancel()
        for running in list(self._running.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await running

    async def _loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            try:
                while len(self._running) < self._concurrency and await self._claim_next():
                    pass
            except Exception:
                logger.exception("Claiming queued work failed")
                await asyncio.sleep(1)
                self._wake.set()

    async def _claim_next(self) -> bool:
        async with self._uow() as uow:
            session = uow._session
            query = (
                select(t.task_queue)
                .where(t.task_queue.c.status == TODO)
                .order_by(t.task_queue.c.id)
            )
            if self._running:
                query = query.where(t.task_queue.c.job_id.not_in(list(self._running)))
            row = (await session.execute(query.limit(1))).mappings().first()
            if row is None:
                return False
            await session.execute(
                update(t.task_queue).where(t.task_queue.c.id == row["id"]).values(status=DOING)
            )
            await uow.commit()
        self._running[row["job_id"]] = asyncio.create_task(self._execute(dict(row)))
        return True

    async def _execute(self, row: dict) -> None:
        status = DONE
        try:
            await self._handlers[row["task"]](row["job_id"], row["revision"], bool(row["start"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task %s of job %s failed", row["task"], row["job_id"])
            status = FAILED
        finally:
            self._running.pop(row["job_id"], None)
        async with self._uow() as uow:
            await uow._session.execute(
                update(t.task_queue).where(t.task_queue.c.id == row["id"]).values(status=status)
            )
            await uow.commit()
        # The job's next task, if any, was waiting for this one.
        self._wake.set()
