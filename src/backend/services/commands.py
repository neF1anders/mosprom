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


async def changed(uow: UnitOfWork, job: Job, message: str) -> None:
    """A new revision and its stage-one job commit together with the change itself."""
    job.updated_at = now()
    job.revision += 1
    job.status = transition(job.status, Status.QUEUED)
    job.error = None
    job.files_changed = False
    job.next_stage = "not_ready"
    job.phase = None
    await uow.jobs.save(job)
    for attachment in await uow.jobs.attachments(job.id):
        if attachment.draft:
            attachment.draft = False
            await uow.jobs.attachment(attachment)
    await uow.queue.stage1(job.id, job.revision)
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="job.changed",
            status=job.status,
            message=message,
        )
    )


async def attached(uow: UnitOfWork, job: Job, message: str, files_changed: bool = True) -> None:
    """File changes wait for the user's next send instead of starting work."""
    job.updated_at = now()
    job.files_changed = files_changed
    await uow.jobs.save(job)
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="job.files_changed",
            status=job.status,
            message=message,
        )
    )


class Commands:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def execute(
        self,
        user_id: str,
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
            job = await uow.jobs.get(job_id, user_id=user_id, lock=True)
            result = await operation(uow, job)
            await uow.jobs.remember(key, digest, result)
            await uow.commit()
            return result
