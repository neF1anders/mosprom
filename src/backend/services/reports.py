"""The assistant's summary closes a finished project in the chat."""

from __future__ import annotations

from ..agents.assistant import Assistant
from ..domain.models import Event, Message
from ..ports.persistence import UowFactory


class Reports:
    def __init__(self, uow: UowFactory, assistant: Assistant):
        self.uow, self.assistant = uow, assistant

    async def post(self, job_id: str) -> None:
        """Written outside any transaction; the report falls back to a template on its own."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
        text = await self.assistant.report(job)
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
            await uow.messages.add(
                Message(
                    job_id=job.id,
                    revision=job.revision,
                    role="assistant",
                    kind="report",
                    text=text,
                )
            )
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="assistant.reported",
                    status=job.status,
                    message="Итоговый отчёт готов",
                )
            )
            await uow.commit()
