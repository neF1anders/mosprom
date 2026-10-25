from __future__ import annotations

import asyncio
import logging

from ..agents.assistant import Assistant
from ..domain.models import Event, Job, Message, now
from ..domain.projects import part_name, project_messages
from ..ports.operations import Files, ResultFolder, ResultFolders
from ..ports.persistence import UowFactory
from .transcript import Entry, entries, render

logger = logging.getLogger(__name__)
# ищем готовый отчёт
RECENT = 20
# весь чат проекта
TRANSCRIPT = 1000
# копии файлов слайсера
KEPT = (("project", "project.3mf"), ("gcode", "result.gcode"))


class Reports:
    def __init__(self, uow: UowFactory, assistant: Assistant, files: Files, folders: ResultFolders):
        self.uow, self.assistant, self.files, self.folders = uow, assistant, files, folders

    async def post(self, job_id: str, revision: int) -> None:
        """Пишет итоговый отчёт ревизии."""
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
            pages = await self._pictures(job, text)
            if not await self._write(job_id, revision, text, folder, made is not None):
                await self.folders.discard(folder)
                return
            for field, name in KEPT:
                if made and made.get(field):
                    await self.folders.write(folder, name, await self.files.read(made[field]))
            for number, page in enumerate(pages, start=1):
                await self.folders.write(folder, f"chat_{number:02d}.png", page)
            await self.folders.write(folder, "report.md", text.encode())
        except BaseException:
            await self.folders.discard(folder)
            raise

    async def _write(
        self, job_id: str, revision: int, text: str, folder: ResultFolder, made: bool
    ) -> bool:
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
            if job.result is not None:
                # показываем папку пользователя
                if made:
                    job.result.folder = folder.shown
                job.result.kept_folder = folder.path.name
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

    async def _pictures(self, job: Job, text: str) -> list[bytes]:
        """Рисует переписку вместе с отчётом."""
        async with self.uow() as uow:
            messages = await uow.messages.list(job.id, None, TRANSCRIPT)
            attachments = await uow.attachments.list(job.id)
        last = max((m.get("seq", 0) for m in messages), default=0)
        report = {"role": "assistant", "kind": "report", "text": text, "seq": last + 1}
        names = {a.id: a.filename for a in attachments}
        shown = entries(project_messages(job, [*messages, report]), names)
        return await asyncio.to_thread(_pictures, part_name(job), shown)


def _pictures(title: str, shown: list[Entry]) -> list[bytes]:
    when = now().astimezone().strftime("%d.%m.%Y %H:%M")
    return render(title, shown, when)
