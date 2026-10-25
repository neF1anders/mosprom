from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..domain.hashing import fingerprint
from ..domain.models import Attachment, Event, Job, Message, Status, now
from ..domain.pipeline import restart
from ..domain.projects import in_project
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork, UowFactory


async def changed(
    uow: UnitOfWork,
    job: Job,
    message: str,
    start: bool = False,
    correction: bool = False,
    typed: list[str] | None = None,
) -> int | None:
    """A new revision and its stage-one job commit together with the change itself.

    ``start`` runs stage one anew; ``correction`` continues the checker's dialog with the new
    text; ``typed`` are messages already in the chat that the run reads as the user's reply.
    Returns where the messages that waited in the queue start in the chat, if any did.
    """
    job.updated_at = now()
    job.revision += 1
    first = await _take_queue(uow, job)
    job.status = transition(job.status, Status.QUEUED)
    job.error = None
    job.files_changed = False
    if job.stage != "done":
        restart(job)
    attachments = await uow.attachments.list(job.id)
    for attachment in attachments:
        if attachment.draft:
            attachment.draft = False
            await uow.attachments.save(attachment)
    await apply_stl(uow, job, attachments)
    await uow.jobs.save(job)
    await uow.queue.cancel_pending(job.id)
    await uow.queue.stage1(job.id, job.revision, start, correction, typed or [])
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="job.changed",
            status=job.status,
            message=message,
        )
    )
    return first


async def _take_queue(uow: UnitOfWork, job: Job) -> int | None:
    """Every new revision takes the messages still waiting, before whatever text started it.

    Nothing is lost or left between revisions; a delivery that claimed them loses its claim.
    """
    waiting = await uow.queued.list(job.id)
    seqs = [
        await uow.messages.add(
            Message(
                job_id=job.id,
                revision=job.revision,
                role="user",
                text=item.text,
                attachment_ids=item.attachment_ids,
                created_at=item.created_at,
            )
        )
        for item in waiting
    ]
    await uow.queued.remove([item.id for item in waiting])
    return seqs[0] if seqs else None


async def apply_stl(uow: UnitOfWork, job: Job, attachments: list[Attachment]) -> None:
    """A sent STL replaces the previous one; until the send, the previous one stays in use.

    Removing an unsent STL therefore leaves the earlier model intact.
    """
    stls = [a for a in attachments if a.active and a.kind == "stl" and in_project(a, job)]
    new = next((a for a in stls if a.id != job.active_stl), None)
    current = next((a for a in stls if a.id == job.active_stl), None)
    if new is not None:
        if current is not None:
            current.active = False
            await uow.attachments.save(current)
        job.active_stl = new.id
    elif current is None and job.active_stl is not None:
        job.active_stl = None


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
            previous = await uow.receipts.find(key, digest)
            if previous is not None:
                return previous
            job = await uow.jobs.get(job_id, user_id=user_id, lock=True)
            result = await operation(uow, job)
            await uow.receipts.remember(key, digest, result)
            await uow.commit()
            return result
