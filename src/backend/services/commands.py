from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..domain.models import Event, Job, Status, now
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork, UowFactory


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def changed(uow: UnitOfWork, job: Job, message: str, *, enqueue: bool = True) -> None:
    job.updated_at = now()
    if enqueue:
        job.revision += 1
        job.status = transition(job.status, Status.QUEUED)
        job.error = None
        job.handoff = "not_ready"
        await uow.queue.enqueue(job)
    await uow.jobs.save(job)
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="job.changed",
            status=job.status,
            message=message,
        )
    )


class Commands:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def execute(
        self,
        job_id: str,
        request_id: str,
        payload: dict[str, Any],
        operation: Callable[[UnitOfWork, Job], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        key, digest = f"{job_id}:{request_id}", fingerprint(payload)
        async with self.uow() as uow:
            previous = await uow.jobs.receipt(key, digest)
            if previous is not None:
                return previous
            job = await uow.jobs.get(job_id, lock=True)
            result = await operation(uow, job)
            await uow.jobs.remember(key, digest, result)
            await uow.commit()
            return result
