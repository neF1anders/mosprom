from __future__ import annotations

from typing import Any

from ..domain.errors import AppError, RevisionConflict
from ..domain.models import Event, Job
from ..ports.persistence import UowFactory
from .commands import fingerprint


class JobService:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def create(self, request_id: str, title: str) -> dict[str, Any]:
        async with self.uow() as uow:
            key, digest = "create:" + request_id, fingerprint(title)
            previous = await uow.jobs.receipt(key, digest)
            if previous is not None:
                return previous
            job = Job(title=title)
            result = job.model_dump(mode="json")
            await uow.jobs.save(job)
            await uow.jobs.remember(key, digest, result)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=0,
                    type="job.created",
                    status="draft",
                    message="Задание создано",
                )
            )
            await uow.commit()
            return result

    async def list(self, before: str | None = None) -> list[dict[str, Any]]:
        async with self.uow() as uow:
            return [
                j.model_dump(mode="json", exclude={"card", "answers", "resolutions"})
                for j in await uow.jobs.list(before)
            ]

    async def snapshot(self, job_id: str, before: int | None = None) -> dict[str, Any]:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
            messages = await uow.jobs.messages(job_id, before)
            attachments = await uow.jobs.attachments(job_id)
            return {
                "job": job.model_dump(mode="json"),
                "messages": messages,
                "attachments": [
                    a.model_dump(exclude={"fragments"}) for a in attachments if a.active
                ],
                "message_cursor": messages[0]["seq"] if len(messages) == 100 else None,
            }

    async def events(self, job_id: str, after: int = 0):
        async with self.uow() as uow:
            await uow.jobs.head(job_id)
            return await uow.events.list(job_id, after)

    async def current_card(self, job_id: str):
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
        if job.card is None:
            raise AppError("Карточка ещё не подготовлена", "card_pending", 409)
        if job.card.revision != job.revision:
            raise RevisionConflict()
        return job.card.model_dump(mode="json")
