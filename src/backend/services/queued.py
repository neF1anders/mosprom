"""Messages typed while the job works wait in a queue the user can edit, delete or send now."""

from __future__ import annotations

from typing import Any

from ..domain.errors import AppError
from ..domain.models import Job, QueuedMessage, now
from ..ports.persistence import UnitOfWork
from .commands import Commands
from .messages import post
from .steering import busy


class QueuedService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def add(self, user_id: str, job_id: str, request_id: str, text: str):
        """While the job works the message waits; otherwise it goes to the assistant at once."""

        async def apply(uow: UnitOfWork, job: Job):
            await post(uow, job, text)
            return await _view(uow, job)

        return await self.commands.execute(user_id, job_id, request_id, {"queue": text}, apply)

    async def edit(self, user_id: str, job_id: str, request_id: str, item_id: str, text: str):
        """A new text starts its attempts afresh; a claim that died goes with the old one."""

        async def apply(uow: UnitOfWork, job: Job):
            item = await _waiting(uow, job, item_id)
            item.text, item.attempts, item.updated_at = text, 0, now()
            item.status, item.claim, item.claimed_at = "queued", None, None
            await uow.queued.save(item)
            return await _view(uow, job)

        payload = {"edit": item_id, "text": text}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)

    async def delete(self, user_id: str, job_id: str, request_id: str, item_id: str):
        async def apply(uow: UnitOfWork, job: Job):
            await uow.queued.remove([(await _waiting(uow, job, item_id)).id])
            return await _view(uow, job)

        payload = {"delete": item_id}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)

    async def send(self, user_id: str, job_id: str, request_id: str, item_id: str):
        """«Скорректировать»: the assistant decides beside the running work, without waiting
        for the step to end, and at once when the job no longer works.

        The whole queue goes, in its order, so no message overtakes an earlier one.
        """

        async def apply(uow: UnitOfWork, job: Job):
            await _waiting(uow, job, item_id)
            await uow.queue.steer(job.id)
            return await _view(uow, job)

        payload = {"send": item_id}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)


def queued_view(items: list[QueuedMessage]) -> list[dict[str, Any]]:
    """What the chat shows of the queue; the claim is the server's own business."""
    return [item.model_dump(mode="json", exclude={"claim", "claimed_at"}) for item in items]


async def _waiting(uow: UnitOfWork, job: Job, item_id: str) -> QueuedMessage:
    """A message still in the queue that no delivery holds right now."""
    item = next((i for i in await uow.queued.list(job.id) if i.id == item_id), None)
    if item is None:
        raise AppError("Сообщение уже отправлено или удалено", "queued_gone", 409)
    if busy(item, now()):
        raise AppError("Сообщение уже доставляется", "queued_busy", 409)
    return item


async def _view(uow: UnitOfWork, job: Job) -> dict[str, Any]:
    return {
        "job": job.model_dump(mode="json"),
        "queued": queued_view(await uow.queued.list(job.id)),
    }
