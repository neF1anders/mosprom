from __future__ import annotations

from ..domain.models import Job, Status
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class ControlService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def run(self, job_id: str, request_id: str, action: str):
        async def apply(uow: UnitOfWork, job: Job):
            if action == "stop":
                target = Status.STOPPING if job.status == Status.RUNNING else Status.STOPPED
                job.status = transition(job.status, target)
                await changed(
                    uow,
                    job,
                    "Останавливаем" if target == Status.STOPPING else "Остановлено",
                    enqueue=False,
                )
            else:
                await changed(uow, job, "Продолжаем обработку")
            return job.model_dump(mode="json")

        return await self.commands.execute(job_id, request_id, {"action": action}, apply)
