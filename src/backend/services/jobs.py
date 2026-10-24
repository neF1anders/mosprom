from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..domain.errors import AppError, RevisionConflict
from ..domain.hashing import fingerprint
from ..domain.models import Event, Job, Status
from ..domain.transitions import transition
from ..ports.operations import Notifier
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import Commands
from .queued import queued_view

EVENT_PAGE = 100
# A quiet stream still sends a heartbeat this often, so proxies and browsers keep it open.
HEARTBEAT_SECONDS = 15


class JobService:
    def __init__(self, uow: UowFactory, notifier: Notifier):
        self.uow, self.notifier = uow, notifier
        self.commands = Commands(uow)

    async def rename(self, user_id: str, job_id: str, request_id: str, title: str):
        async def apply(uow: UnitOfWork, job: Job):
            job.title, job.title_source = title.strip()[:80] or job.title, "user"
            await uow.jobs.save(job)
            return job.model_dump(mode="json", exclude={"card", "answers"})

        return await self.commands.execute(user_id, job_id, request_id, {"title": title}, apply)

    async def delete(self, user_id: str, job_id: str, request_id: str):
        async def apply(uow: UnitOfWork, job: Job):
            job.deleted = True
            # A running reading stops at its next safe point instead of spending tokens.
            if job.status == Status.RUNNING:
                job.status = transition(job.status, Status.STOPPING)
            elif job.status == Status.QUEUED:
                job.status = transition(job.status, Status.STOPPED)
            await uow.jobs.save(job)
            return {"id": job.id, "deleted": True}

        return await self.commands.execute(user_id, job_id, request_id, {"delete": True}, apply)

    async def create(self, user_id: str, request_id: str, title: str) -> dict[str, Any]:
        async with self.uow() as uow:
            key, digest = f"create:{user_id}:{request_id}", fingerprint(title)
            previous = await uow.receipts.find(key, digest)
            if previous is not None:
                return previous
            job = Job(user_id=user_id, title=title)
            result = job.model_dump(mode="json")
            await uow.jobs.save(job)
            await uow.receipts.remember(key, digest, result)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=0,
                    type="job.created",
                    status=job.status,
                    message="Задание создано",
                )
            )
            await uow.commit()
            return result

    async def list(self, user_id: str, before: str | None = None) -> list[dict[str, Any]]:
        async with self.uow() as uow:
            return [
                j.model_dump(mode="json", exclude={"card", "answers"})
                for j in await uow.jobs.list(user_id, before)
            ]

    async def snapshot(
        self, user_id: str, job_id: str, before: int | None = None
    ) -> dict[str, Any]:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
            messages = await uow.messages.list(job_id, before)
            attachments = await uow.attachments.list(job_id)
            queued = await uow.queued.list(job_id)
        # The full STL report is for the card export and stage two, not for the chat view.
        return {
            "job": job.model_dump(mode="json", exclude={"card": {"stl_analysis"}}),
            "messages": messages,
            "queued": queued_view(queued),
            "attachments": [
                a.model_dump(mode="json", exclude={"fragments"}) for a in attachments if a.active
            ],
            "message_cursor": messages[0]["seq"] if len(messages) == 100 else None,
        }

    async def follow(
        self, user_id: str, job_id: str, after: int | None
    ) -> AsyncIterator[Event | None]:
        """Events after the cursor, then each new one as it commits; None is a heartbeat.

        Without a cursor the stream starts at the revision of the job's work: older history
        is never shown, so it is not replayed on every open.
        """
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
            start = job.work_revision
            cursor = after if after is not None else await uow.events.start(job_id, start)
        return self._stream(job_id, cursor)

    async def _stream(self, job_id: str, cursor: int) -> AsyncIterator[Event | None]:
        async with self.notifier.watch(job_id) as changed:
            while True:
                # Cleared before the read: an event committed after it wakes the wait below.
                changed.clear()
                async with self.uow() as uow:
                    batch = await uow.events.list(job_id, cursor, EVENT_PAGE)
                for event in batch:
                    cursor = event.event_id
                    yield event
                if len(batch) == EVENT_PAGE:
                    continue
                try:
                    await asyncio.wait_for(changed.wait(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield None

    async def current_card(self, user_id: str, job_id: str) -> dict[str, Any]:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
        if job.card is None:
            raise AppError("Карточка ещё не подготовлена", "card_pending", 409)
        if job.card.revision != job.revision:
            raise RevisionConflict()
        return job.card.model_dump(mode="json")

    async def current_parameters(self, user_id: str, job_id: str) -> dict[str, Any]:
        """The latest parameter set of the job's work, as the check and the slicer read it."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
            found = await uow.stage_results.latest(job.id, job.work_revision, "parameters")
        if found is None:
            raise AppError("Параметры ещё не подобраны", "parameters_pending", 409)
        return found
