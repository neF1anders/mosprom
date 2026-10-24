"""Procrastinate task handlers, bound to the worker's container."""

from __future__ import annotations

from .container import Container
from .infrastructure.queue import (
    STAGE1_QUEUE,
    STAGE1_TASK,
    STAGE2_QUEUE,
    STAGE2_TASK,
    STEER_QUEUE,
    STEER_TASK,
)


def register(container: Container) -> None:
    @container.queue.task(name=STAGE1_TASK, queue=STAGE1_QUEUE)
    async def stage1(
        job_id: str, revision: int, start: bool = False, correction: bool = False
    ) -> None:
        await container.stage1.run(job_id, revision, start, correction)

    @container.queue.task(name=STAGE2_TASK, queue=STAGE2_QUEUE)
    async def parameters(job_id: str, revision: int) -> None:
        await container.pipeline.run(job_id, revision)

    @container.queue.task(name=STEER_TASK, queue=STEER_QUEUE)
    async def steer(job_id: str) -> None:
        await container.steering.deliver(job_id, force=True)
