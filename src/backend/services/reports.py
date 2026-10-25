"""The assistant's summary closes a finished project in the chat."""

from __future__ import annotations

import logging

from ..agents.assistant import Assistant
from ..domain.models import Event, Message
from ..ports.persistence import UowFactory

logger = logging.getLogger(__name__)
# A report is looked for among the latest messages before another one is written.
RECENT = 20


class Reports:
    def __init__(self, uow: UowFactory, assistant: Assistant):
        self.uow, self.assistant = uow, assistant

    async def post(self, job_id: str, revision: int) -> None:
        """Written once for the revision that finished, and only while it is current.

        The project is done whatever happens here: a failure is logged and never fails it.
        """
        try:
            await self._post(job_id, revision)
        except Exception:
            logger.exception("The report of job %s revision %s was not written", job_id, revision)

    async def _post(self, job_id: str, revision: int) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
        text = await self.assistant.report(job)
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            recent = await uow.messages.list(job_id, None, RECENT)
            written = any(
                m.get("kind") == "report" and m.get("revision") == revision for m in recent
            )
            if job.revision != revision or written:
                return
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
