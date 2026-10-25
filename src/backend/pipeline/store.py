from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..domain.errors import OperationCancelled
from ..domain.models import Event, Job, Status
from ..domain.transitions import transition
from ..ports.persistence import UowFactory

HALTED = {Status.STOPPING, Status.STOPPED}
# доставка между шагами
SafePoint = Callable[[str, int], Awaitable[bool]]


async def no_safe_point(job_id: str, revision: int) -> bool:
    return False


def ensure_current(revision: int, status: Status, expected: int) -> None:
    """Прерывает устаревшую работу."""
    if revision != expected or status in HALTED:
        raise OperationCancelled()


class JobStore:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def update(self, job_id: str, revision: int, change: Callable[[Job], None]) -> Job:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            ensure_current(job.revision, job.status, revision)
            change(job)
            await uow.jobs.save(job)
            await uow.commit()
        return job

    async def check(self, job_id: str, revision: int) -> None:
        async with self.uow() as uow:
            head = await uow.jobs.head(job_id)
        ensure_current(head.revision, head.status, revision)

    async def event(
        self, job_id: str, revision: int, type: str, message: str, status: str = "running", **data
    ) -> None:
        async with self.uow() as uow:
            await uow.events.append(
                Event(
                    job_id=job_id,
                    revision=revision,
                    type=type,
                    status=status,
                    message=message,
                    data=data,
                )
            )
            await uow.commit()

    async def cancel(self, job_id: str) -> None:
        """Применяет остановку пользователя."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            if job.status != Status.STOPPING:
                return
            job.status = transition(job.status, Status.STOPPED)
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="job.stopped",
                    status=job.status,
                    message="Остановлено",
                )
            )
            await uow.commit()

    async def fail(self, job_id: str, revision: int, message: str, code: str) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            if job.revision != revision:
                return
            if job.status in HALTED:
                job.status = Status.STOPPED
            else:
                job.status, job.error = transition(job.status, Status.FAILED), message
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="operation.failed",
                    status=job.status,
                    message=message,
                    data={"code": code},
                )
            )
            await uow.commit()
