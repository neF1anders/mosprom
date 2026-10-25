from __future__ import annotations

from ..domain.errors import AppError
from ..domain.models import Event, Job, Message, QueuedMessage, Status, now
from ..ports.persistence import UnitOfWork
from .commands import Commands

# сообщение ждёт шага
WORKING = {Status.QUEUED, Status.RUNNING}
LIMIT = 10


class MessageService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def send(self, user_id: str, job_id: str, request_id: str, text: str):
        async def apply(uow: UnitOfWork, job: Job):
            await post(uow, job, text)
            return job.model_dump(mode="json")

        return await self.commands.execute(user_id, job_id, request_id, {"text": text}, apply)


async def post(uow: UnitOfWork, job: Job, text: str) -> None:
    """Отправляет сообщение ассистенту с файлами."""
    if job.title_source == "auto" and job.title == "Новое задание" and text.strip():
        job.title = text[:80]
    sent = await _send_files(uow, job)
    if not text.strip() and not sent:
        raise AppError("Напишите сообщение или приложите файл", "empty_message", 422)
    job.updated_at = now()
    await uow.jobs.save(job)
    if job.status in WORKING:
        await enqueue(uow, job, text, sent)
        return
    await uow.messages.add(
        Message(job_id=job.id, revision=job.revision, role="user", text=text, attachment_ids=sent)
    )
    await _event(uow, job, "message.added", "Сообщение принято")
    await uow.queue.steer(job.id)


async def _send_files(uow: UnitOfWork, job: Job) -> list[str]:
    """Прикладывает ожидающие файлы к сообщению."""
    sent = []
    for attachment in await uow.attachments.list(job.id):
        if not attachment.draft:
            continue
        attachment.draft = False
        await uow.attachments.save(attachment)
        if attachment.active:
            sent.append(attachment.id)
    return sent


async def enqueue(uow: UnitOfWork, job: Job, text: str, attachment_ids: list[str]) -> None:
    if len(await uow.queued.list(job.id)) >= LIMIT:
        raise AppError(f"В очереди может быть не больше {LIMIT} сообщений", "queue_full", 409)
    item = QueuedMessage(job_id=job.id, text=text, attachment_ids=attachment_ids)
    await uow.queued.save(item)
    await _event(uow, job, "queue.added", "Сообщение ждёт конца текущего шага", id=item.id)


async def _event(uow: UnitOfWork, job: Job, type: str, message: str, **data: str) -> None:
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type=type,
            status=job.status,
            message=message,
            data=data,
        )
    )
