from __future__ import annotations

from ..domain.models import Job, Message
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class MessageService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def send(self, job_id: str, request_id: str, text: str, intent: str = "message"):
        async def apply(uow: UnitOfWork, job: Job):
            is_status = intent == "status" or text.strip().casefold() in {
                "что сейчас происходит?",
                "какой статус?",
                "статус",
            }
            await changed(
                uow,
                job,
                "Сообщение принято" if not is_status else "Статус задания получен",
                enqueue=not is_status,
            )
            await uow.jobs.message(
                Message(job_id=job.id, revision=job.revision, role="user", text=text)
            )
            if is_status:
                await uow.jobs.message(
                    Message(
                        job_id=job.id,
                        revision=job.revision,
                        role="assistant",
                        text=f"Текущее состояние {job.status}",
                    )
                )
            if job.title == "Новое задание" and not is_status:
                job.title = text[:80]
                await uow.jobs.save(job)
            return job.model_dump(mode="json")

        return await self.commands.execute(
            job_id, request_id, {"text": text, "intent": intent}, apply
        )
