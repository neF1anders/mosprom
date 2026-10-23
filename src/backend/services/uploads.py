from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import PurePath

from ..domain.errors import AppError
from ..domain.limits import LIMITS, InputLimits
from ..domain.models import Attachment, Job, identifier
from ..ports.operations import Files
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import Commands, changed


class UploadService:
    def __init__(
        self, commands: Commands, files: Files, uow: UowFactory, limits: InputLimits | None = None
    ):
        self.commands, self.files, self.uow = commands, files, uow
        self.limits = limits or InputLimits()

    async def upload(
        self, job_id: str, request_id: str, filename: str, chunks: AsyncIterator[bytes]
    ):
        kind = PurePath(filename).suffix.lower().lstrip(".")
        if kind not in LIMITS:
            raise AppError("Поддерживаются STL, PDF, DOCX, TXT, MD, JPG и PNG", "unsupported_type")
        async with self.uow() as uow:
            await uow.jobs.get(job_id)
        key = identifier()
        digest, size = await self.files.put(key, chunks, self.limits.file_mib(kind) * 1024 * 1024)
        attachment = Attachment(
            id=key,
            job_id=job_id,
            filename=PurePath(filename.replace("\\", "/")).name[:255],
            kind=kind,
            sha256=digest,
            size=size,
        )

        async def apply(uow: UnitOfWork, job: Job):
            existing = await uow.jobs.attachments(job_id)
            if (
                kind != "stl"
                and sum(a.kind != "stl" and a.active for a in existing) >= self.limits.companions
            ):
                raise AppError(
                    f"Можно приложить до {self.limits.companions} сопроводительных файлов",
                    "attachment_limit",
                    413,
                )
            await uow.jobs.attachment(attachment)
            if kind == "stl":
                job.active_stl = attachment.id
                job.units = "unknown"
                job.answers.pop("geometry.units", None)
            await changed(uow, job, "Файл принят, проверка в очереди")
            return attachment.model_dump()

        try:
            result = await self.commands.execute(
                job_id, request_id, {"filename": filename, "sha256": digest}, apply
            )
        except BaseException:
            await self.files.remove(key)
            raise
        if result["id"] != key:
            await self.files.remove(key)
        return result

    async def detach(self, job_id: str, request_id: str, attachment_id: str):
        async def apply(uow: UnitOfWork, job: Job):
            attachments = await uow.jobs.attachments(job_id)
            attachment = next((a for a in attachments if a.id == attachment_id), None)
            if attachment is None:
                raise AppError("Вложение не найдено", "not_found", 404)
            attachment.active = False
            await uow.jobs.attachment(attachment)
            if job.active_stl == attachment_id:
                job.active_stl = None
                job.units = "unknown"
            await changed(uow, job, "Вложение исключено из текущего задания")
            return job.model_dump(mode="json")

        return await self.commands.execute(job_id, request_id, {"detach": attachment_id}, apply)
