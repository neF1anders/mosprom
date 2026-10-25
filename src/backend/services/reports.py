"""The assistant's summary closes a finished project in the chat.

The project's files go to a folder of its own, named after the part, with the report and
pictures of the chat: what the assistant asked, what the user answered and what came of it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..agents.assistant import Assistant
from ..domain.models import Event, Job, Message, now
from ..domain.projects import part_name, project_messages
from ..ports.operations import Files, ResultFolder, ResultFolders
from ..ports.persistence import UowFactory
from .transcript import entries, render

logger = logging.getLogger(__name__)
# A report is looked for among the latest messages before another one is written.
RECENT = 20
# The chat of one project, however long it went on.
TRANSCRIPT = 1000
# The stored copies of the slicer's files and the names they are kept under.
KEPT = (("project", "project.3mf"), ("gcode", "result.gcode"))


class Reports:
    def __init__(self, uow: UowFactory, assistant: Assistant, files: Files, folders: ResultFolders):
        self.uow, self.assistant, self.files, self.folders = uow, assistant, files, folders

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
            sliced = await uow.stage_results.latest(job.id, job.work_revision, "slicing")
        made = sliced if sliced and sliced.get("status") == "sliced" else None
        folder = await self.folders.reserve(part_name(job))
        try:
            text = await self.assistant.report(job, folder.shown if made else None)
            if not await self._write(job_id, revision, text, folder.shown if made else None):
                await self.folders.discard(folder)
                return
            await self._keep(folder, job_id, text, made)
        except BaseException:
            await self.folders.discard(folder)
            raise

    async def _write(self, job_id: str, revision: int, text: str, shown: str | None) -> bool:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            recent = await uow.messages.list(job_id, None, RECENT)
            written = any(
                m.get("kind") == "report" and m.get("revision") == revision for m in recent
            )
            if job.revision != revision or written:
                return False
            await uow.messages.add(
                Message(
                    job_id=job.id,
                    revision=job.revision,
                    role="assistant",
                    kind="report",
                    text=text,
                )
            )
            if shown and job.result is not None:
                # The chat shows the folder the user keeps, not the one shared with the slicer.
                job.result.folder = shown
                await uow.jobs.save(job)
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
        return True

    async def _keep(
        self, folder: ResultFolder, job_id: str, text: str, sliced: dict[str, Any] | None
    ) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
            messages = await uow.messages.list(job_id, None, TRANSCRIPT)
            attachments = await uow.attachments.list(job_id)
        for field, name in KEPT if sliced else ():
            if sliced and sliced.get(field):
                await self.folders.write(folder, name, await self.files.read(sliced[field]))
        await self.folders.write(folder, "report.md", text.encode())
        names = {a.id: a.filename for a in attachments}
        pages = await asyncio.to_thread(_pictures, job, project_messages(job, messages), names)
        for number, page in enumerate(pages, start=1):
            await self.folders.write(folder, f"chat_{number:02d}.png", page)


def _pictures(job: Job, messages: list[dict[str, Any]], names: dict[str, str]) -> list[bytes]:
    when = now().astimezone().strftime("%d.%m.%Y %H:%M")
    return render(part_name(job), entries(messages, names), when)
