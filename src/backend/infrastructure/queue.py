from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import tables as t

logger = logging.getLogger(__name__)

STAGE1_TASK = "stage1.run"
# подбор и проверка
STAGE2_TASK = "stage2.select_parameters"
# доставка очереди сообщений
STEER_TASK = "steer.deliver"
TODO, DOING, DONE, FAILED, CANCELLED = "todo", "doing", "done", "failed", "cancelled"


class SqlQueue:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def stage1(
        self,
        job_id: str,
        revision: int,
        start: bool = False,
        correction: bool = False,
        typed: list[str] | None = None,
    ) -> None:
        arguments: dict[str, Any] = {"job_id": job_id, "revision": revision, "start": start}
        # флаги только коррекции
        if correction:
            arguments["correction"] = True
        if typed:
            arguments["typed"] = typed
        await self._add(STAGE1_TASK, _lock(job_id), job_id, arguments)

    async def stage2(self, job_id: str, revision: int) -> None:
        arguments = {"job_id": job_id, "revision": revision}
        await self._add(STAGE2_TASK, _lock(job_id), job_id, arguments)

    async def steer(self, job_id: str) -> None:
        """Отдельная блокировка для доставки сообщений."""
        await self._add(STEER_TASK, f"steer:{job_id}", job_id, {"job_id": job_id})

    async def cancel_pending(self, job_id: str) -> None:
        """Снимает устаревшую работу прошлых ревизий."""
        await self._session.execute(
            update(t.task_queue)
            .where(t.task_queue.c.lock == _lock(job_id), t.task_queue.c.status == TODO)
            .values(status=CANCELLED)
        )

    async def _add(self, task: str, lock: str, job_id: str, arguments: dict[str, Any]) -> None:
        await self._session.execute(
            t.task_queue.insert().values(
                task=task, lock=lock, job_id=job_id, args=arguments, status=TODO
            )
        )
        self._session.info["wake"] = True


def _lock(job_id: str) -> str:
    """Блокировка на каждую задачу."""
    return f"job:{job_id}"


# аргументы из payload
Handler = Callable[..., Awaitable[None]]


class TaskRunner:
    """Исполнитель очереди с блокировками."""

    def __init__(self, uow, wake: asyncio.Event, handlers: dict[str, Handler], concurrency: int):
        self._uow, self._wake, self._handlers = uow, wake, handlers
        self._concurrency = concurrency
        self._running: dict[str, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        # обработчики идемпотентны
        async with self._uow() as uow:
            await uow._session.execute(
                update(t.task_queue).where(t.task_queue.c.status == DOING).values(status=TODO)
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
                query = query.where(t.task_queue.c.lock.not_in(list(self._running)))
            row = (await session.execute(query.limit(1))).mappings().first()
            if row is None:
                return False
            await session.execute(
                update(t.task_queue).where(t.task_queue.c.id == row["id"]).values(status=DOING)
            )
            await uow.commit()
        self._running[row["lock"]] = asyncio.create_task(self._execute(dict(row)))
        return True

    async def _execute(self, row: dict) -> None:
        status = DONE
        try:
            await self._handlers[row["task"]](**row["args"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task %s of job %s failed", row["task"], row["job_id"])
            status = FAILED
        finally:
            self._running.pop(row["lock"], None)
        async with self._uow() as uow:
            await uow._session.execute(
                update(t.task_queue).where(t.task_queue.c.id == row["id"]).values(status=status)
            )
            await uow.commit()
        self._wake.set()
