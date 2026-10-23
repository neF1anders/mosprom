from __future__ import annotations

from typing import Any

from ..domain.errors import AppError, RevisionConflict
from ..domain.models import Event, Job, Status
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import Commands, fingerprint


class JobService:
    def __init__(self, uow: UowFactory):
        self.uow = uow
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
            previous = await uow.jobs.receipt(key, digest)
            if previous is not None:
                return previous
            job = Job(user_id=user_id, title=title)
            result = job.model_dump(mode="json")
            await uow.jobs.save(job)
            await uow.jobs.remember(key, digest, result)
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
            messages = await uow.jobs.messages(job_id, before)
            attachments = await uow.jobs.attachments(job_id)
        return {
            "job": job.model_dump(mode="json"),
            "messages": messages,
            "attachments": [
                a.model_dump(mode="json", exclude={"fragments"}) for a in attachments if a.active
            ],
            "message_cursor": messages[0]["seq"] if len(messages) == 100 else None,
        }

    async def ensure_owner(self, user_id: str, job_id: str) -> None:
        async with self.uow() as uow:
            await uow.jobs.get(job_id, user_id=user_id)

    async def events(self, job_id: str, after: int = 0):
        async with self.uow() as uow:
            return await uow.events.list(job_id, after)

    async def current_card(self, user_id: str, job_id: str) -> dict[str, Any]:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
        if job.card is None:
            raise AppError("Карточка ещё не подготовлена", "card_pending", 409)
        if job.card.revision != job.revision:
            raise RevisionConflict()
        return job.card.model_dump(mode="json")
