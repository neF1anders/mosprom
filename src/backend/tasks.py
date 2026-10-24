"""Procrastinate task handlers, bound to the worker's container."""

from __future__ import annotations

from .container import Container
from .infrastructure.queue import STAGE1_QUEUE, STAGE1_TASK


def register(container: Container) -> None:
    @container.queue.task(name=STAGE1_TASK, queue=STAGE1_QUEUE)
    async def stage1(job_id: str, revision: int) -> None:
        await container.stage1.run(job_id, revision)
