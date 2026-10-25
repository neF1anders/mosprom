from __future__ import annotations

from typing import Any, Literal

from ..domain.errors import AppError, NotFound
from ..domain.pipeline import Step
from ..ports.operations import Files, ResultFolders
from ..ports.persistence import UowFactory

ResultFile = Literal["gcode", "project"]
# поле отчёта
RESULT_FILES = {"gcode": ("gcode", "result.gcode"), "project": ("project", "project.3mf")}


class ArtifactService:
    def __init__(self, uow: UowFactory, files: Files, folders: ResultFolders):
        self.uow, self.files, self.folders = uow, files, folders

    async def read(self, user_id: str, job_id: str, artifact_id: str) -> bytes:
        async with self.uow() as uow:
            await uow.jobs.get(job_id, user_id=user_id)
            attachments = await uow.attachments.list(job_id)
        allowed = {a.id for a in attachments}
        allowed.update(key for a in attachments for key in a.artifacts)
        if artifact_id not in allowed:
            raise NotFound()
        return await self.files.read(artifact_id)

    async def result(self, user_id: str, job_id: str, kind: ResultFile) -> tuple[bytes, str]:
        """Результат последней нарезки задачи."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
            report = None
            if job.result is not None and job.result.sliced:
                step = Step("slicing", job.result.iteration)
                report = await uow.stage_results.get(job.id, job.work_revision, step)
        field, filename = RESULT_FILES[kind]
        if not report or not report.get(field):
            raise AppError("Проект ещё не создан", "result_pending", 409)
        return await self.files.read(report[field]), filename

    async def kept_files(self, user_id: str, job_id: str) -> dict[str, Any]:
        """Содержимое папки проекта сейчас."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
        folder = job.result.kept_folder if job.result else None
        files = await self.folders.files(folder) if folder else None
        return {"folder": folder, "exists": files is not None, "files": files or []}

    async def kept(self, user_id: str, job_id: str, name: str) -> bytes:
        """Файл из папки проекта."""
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, user_id=user_id)
        folder = job.result.kept_folder if job.result else None
        if not folder:
            raise NotFound()
        return await self.folders.read(folder, name)
