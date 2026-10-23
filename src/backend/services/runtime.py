from __future__ import annotations

from ..domain.errors import OperationCancelled
from ..domain.models import Event, Status, Work
from ..ports.persistence import UowFactory


class Runtime:
    def __init__(self, uow: UowFactory, work: Work):
        self.uow, self.work = uow, work
        self.calls = 0

    async def check(self) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.head(self.work.job_id)
        if job.revision != self.work.revision or job.status in {Status.STOPPING, Status.STOPPED}:
            raise OperationCancelled()

    async def event(self, type: str, message: str, status: str = "running", **data) -> None:
        async with self.uow() as uow:
            await uow.events.append(
                Event(
                    job_id=self.work.job_id,
                    revision=self.work.revision,
                    type=type,
                    status=status,
                    message=message,
                    data=data,
                )
            )
            await uow.commit()
