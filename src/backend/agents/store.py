"""Every database step of a stage-one run, each in its own short transaction."""

from __future__ import annotations

from typing import Any

from ..domain.models import Attachment, Event, Job, Knowledge, Message, Status, TaskCard
from ..domain.pipeline import restart
from ..domain.transitions import transition
from ..pipeline.store import JobStore, ensure_current
from ..ports.persistence import UnitOfWork
from .runner import RunContext

PAGE = 100
FILES_CHANGED = "Файлы изменились, отправьте задание, чтобы я их учёл"


class RunStore(JobStore):
    """Stage one's reads and writes on top of the steps every stage shares."""

    async def job(self, job_id: str) -> Job:
        async with self.uow() as uow:
            return await uow.jobs.get(job_id)

    async def attachments(self, job_id: str) -> list[Attachment]:
        async with self.uow() as uow:
            return await uow.attachments.list(job_id)

    async def messages(self, job_id: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        before = None
        while True:
            async with self.uow() as uow:
                page = await uow.messages.list(job_id, before, PAGE)
            messages = page + messages
            if len(page) < PAGE:
                return messages
            before = page[0]["seq"]

    async def knowledge(self) -> list[Knowledge]:
        async with self.uow() as uow:
            return await uow.knowledge.all()

    async def cached(self, key: str) -> dict[str, Any] | None:
        async with self.uow() as uow:
            return await uow.cache.get(key)

    async def cache(self, key: str, value: dict[str, Any]) -> None:
        async with self.uow() as uow:
            await uow.cache.put(key, value)
            await uow.commit()

    async def save(self, attachment: Attachment) -> None:
        async with self.uow() as uow:
            await uow.attachments.save(attachment)
            await uow.commit()

    async def begin(self, ctx: RunContext) -> None:
        """The work starts in this revision, so whatever the previous work made is dropped."""
        await self.update(ctx.job_id, ctx.revision, restart)

    async def finish(self, ctx: RunContext, card: TaskCard, text: str) -> None:
        """Publishes the card the work made; a ready card goes on to parameter selection."""
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            ensure_current(job.revision, job.status, ctx.revision)
            job.card = card
            await _hand_over(uow, job)
            await _publish(uow, job, FILES_CHANGED if job.files_changed else text, "chat")
            await uow.commit()

    async def reply(self, ctx: RunContext, text: str, kind: str, current: bool) -> None:
        """The gate's reply when it starts no work; ``kind`` marks its request for details.

        The card of the files the job still has stays, and so does a project finished from
        it; work left unfinished goes on. A card of other files no longer describes the part.
        """
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            ensure_current(job.revision, job.status, ctx.revision)
            if job.card is not None and not current:
                job.card = None
                restart(job)
            elif job.card is not None:
                job.card = job.card.model_copy(update={"revision": job.revision})
            if job.stage == "done":
                job.status = transition(job.status, Status.COMPLETED)
            else:
                await _hand_over(uow, job)
            await _publish(uow, job, FILES_CHANGED if job.files_changed else text, kind)
            await uow.commit()


async def _hand_over(uow: UnitOfWork, job: Job) -> None:
    """A ready card waits in the queue for parameter selection, in the same transaction.

    Files attached during the run are not in the card, so it waits for the user's send.
    """
    blocked = job.card is None or job.card.readiness == "blocked" or job.files_changed
    job.status = transition(job.status, Status.WAITING if blocked else Status.QUEUED)
    if not blocked:
        await uow.queue.stage2(job.id, job.revision)
        job.stage, job.work_revision = "parameters", job.revision


async def _publish(uow: UnitOfWork, job: Job, text: str, kind: str) -> None:
    await uow.jobs.save(job)
    await uow.messages.add(
        Message(
            job_id=job.id,
            revision=job.revision,
            role="assistant",
            kind=kind,  # type: ignore[arg-type]
            text=text,
        )
    )
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="stage1.completed",
            status=job.status,
            message=text,
            data={"readiness": job.card.readiness if job.card else "blocked"},
        )
    )
