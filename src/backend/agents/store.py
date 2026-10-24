"""Every database step of a stage-one run, each in its own short transaction."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..domain.errors import OperationCancelled
from ..domain.models import Attachment, Event, Job, Knowledge, Message, Status, TaskCard
from ..domain.transitions import transition
from ..ports.persistence import UowFactory
from .runner import RunContext

HALTED = {Status.STOPPING, Status.STOPPED}
PAGE = 100


def _ensure_current(revision: int, status: Status, expected: int) -> None:
    """A newer revision or a stop ends the run at its next safe point."""
    if revision != expected or status in HALTED:
        raise OperationCancelled()


class RunStore:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def update(self, ctx: RunContext, change: Callable[[Job], None]) -> Job:
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            _ensure_current(job.revision, job.status, ctx.revision)
            change(job)
            await uow.jobs.save(job)
            await uow.commit()
        return job

    async def check(self, job_id: str, revision: int) -> None:
        async with self.uow() as uow:
            head = await uow.jobs.head(job_id)
        _ensure_current(head.revision, head.status, revision)

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

    async def event(
        self, job_id: str, revision: int, type: str, message: str, status: str = "running", **data
    ) -> None:
        async with self.uow() as uow:
            await uow.events.append(
                Event(
                    job_id=job_id,
                    revision=revision,
                    type=type,
                    status=status,
                    message=message,
                    data=data,
                )
            )
            await uow.commit()

    async def finish(
        self, ctx: RunContext, card: TaskCard | None, text: str, offtopic: str | None = None
    ) -> None:
        """Publishes the card and the reply; a ready card goes on to stage two."""
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            _ensure_current(job.revision, job.status, ctx.revision)
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

    async def cancel(self, job_id: str) -> None:
        """A stop requested during the run takes effect here; the event tells open chats."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            if job.status != Status.STOPPING:
                return
            job.status = transition(job.status, Status.STOPPED)
            job.phase = None
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="job.stopped",
                    status=job.status,
                    message="Остановлено",
                )
            )
            await uow.commit()

    async def fail(self, ctx: RunContext, message: str, code: str) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            if job.revision != ctx.revision:
                return
            if job.status in HALTED:
                job.status = Status.STOPPED
            else:
                job.status, job.error = transition(job.status, Status.FAILED), message
            job.phase = None
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="operation.failed",
                    status=job.status,
                    message=message,
                    data={"code": code},
                )
            )
            await uow.commit()
