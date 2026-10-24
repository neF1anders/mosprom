"""Every database step of a stage-one run, each in its own short transaction."""

from __future__ import annotations

from typing import Any

from ..domain.models import Attachment, Event, Job, Knowledge, Message, Status, TaskCard
from ..domain.transitions import transition
from ..pipeline.store import JobStore, ensure_current
from .runner import RunContext

PAGE = 100


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

    async def finish(
        self, ctx: RunContext, card: TaskCard | None, text: str, offtopic: str | None = None
    ) -> None:
        """Publishes the card and the reply; a ready card goes on to stage two."""
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            ensure_current(job.revision, job.status, ctx.revision)
            # Files attached during the run are not in this card, so it is not handed over.
            if job.files_changed:
                text = "Файлы изменились, отправьте задание, чтобы я их учёл"
            blocked = card is None or card.readiness == "blocked" or job.files_changed
            job.card, job.error, job.phase = card, None, None
            job.status = transition(job.status, Status.WAITING if blocked else Status.COMPLETED)
            if not blocked:
                await uow.queue.stage2(job.id, job.revision)
                job.next_stage = "queued"
            await uow.jobs.save(job)
            if offtopic is not None:
                await uow.messages.mark(job.id, offtopic, "offtopic")
            await uow.messages.add(
                Message(job_id=job.id, revision=job.revision, role="assistant", text=text)
            )
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="stage1.completed",
                    status=job.status,
                    message=text,
                    data={"readiness": card.readiness if card else "blocked"},
                )
            )
            await uow.commit()
