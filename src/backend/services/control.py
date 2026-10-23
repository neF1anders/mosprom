from __future__ import annotations

from pathlib import PurePath
from typing import Literal

from ..domain.models import Event, Job, Status
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class ControlService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def run(
        self, user_id: str, job_id: str, request_id: str, action: Literal["stop", "retry"]
    ):
        async def apply(uow: UnitOfWork, job: Job):
            if action == "retry":
                await name_from_files(uow, job)
                await changed(uow, job, "Продолжаем обработку")
                return job.model_dump(mode="json")
            # Running work stops at its next safe point; anything else stops at once.
            target = Status.STOPPING if job.status == Status.RUNNING else Status.STOPPED
            if job.status != Status.STOPPING:
                job.status = transition(job.status, target)
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="job.stopping" if job.status == Status.STOPPING else "job.stopped",
                    status=job.status,
                    message="Останавливаю" if job.status == Status.STOPPING else "Остановлено",
                )
            )
            return job.model_dump(mode="json")

        return await self.commands.execute(user_id, job_id, request_id, {"action": action}, apply)


async def name_from_files(uow: UnitOfWork, job: Job) -> None:
    """Files sent without a message still name the chat at once; a document beats the STL."""
    if job.title_source != "auto" or job.title != "Новое задание":
        return
    files = sorted(
        (a for a in await uow.jobs.attachments(job.id) if a.active), key=lambda a: a.kind == "stl"
    )
    if files:
        job.title = PurePath(files[0].filename).stem[:80] or job.title
