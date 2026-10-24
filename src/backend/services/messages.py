from __future__ import annotations

from ..domain.models import Job, Message
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class MessageService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def send(self, user_id: str, job_id: str, request_id: str, text: str):
        async def apply(uow: UnitOfWork, job: Job):
            await post(uow, job, text)
            return job.model_dump(mode="json")

        return await self.commands.execute(user_id, job_id, request_id, {"text": text}, apply)


async def post(uow: UnitOfWork, job: Job, text: str) -> None:
    """The user's message starts a new revision; the first one names the chat."""
    if job.title_source == "auto" and job.title == "Новое задание":
        job.title = text[:80]
    await changed(uow, job, "Сообщение принято")
    await uow.messages.add(Message(job_id=job.id, revision=job.revision, role="user", text=text))
