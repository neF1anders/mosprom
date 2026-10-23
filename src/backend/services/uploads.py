from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import PurePath

from ..domain.errors import AppError
from ..domain.limits import KINDS, InputLimits
from ..domain.models import Attachment, Job, identifier
from ..ports.operations import Files
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import Commands, attached


def reset_units(job: Job) -> None:
    """A different STL needs its scale confirmed again."""
    job.units = "unknown"
    job.answers.pop("units", None)


class UploadService:
    def __init__(self, commands: Commands, files: Files, uow: UowFactory, limits: InputLimits):
        self.commands, self.files, self.uow, self.limits = commands, files, uow, limits

    async def upload(
        self,
        user_id: str,
        job_id: str,
        request_id: str,
        filename: str,
        chunks: AsyncIterator[bytes],
    ):
        kind = PurePath(filename).suffix.lower().lstrip(".")
        if kind not in KINDS:
            raise AppError("Поддерживаются STL, PDF, DOCX, TXT, MD, JPG и PNG", "unsupported_type")
        async with self.uow() as uow:
            await uow.jobs.get(job_id, user_id=user_id)
        key = identifier()
        digest, size = await self.files.put(key, chunks, self.limits.file_mib(kind) * 1024 * 1024)
        attachment = Attachment(
            id=key,
            job_id=job_id,
            filename=PurePath(filename.replace("\\", "/")).name[:255],
            kind=kind,
            sha256=digest,
            size=size,
            draft=True,
        )

        async def apply(uow: UnitOfWork, job: Job):
            existing = await uow.jobs.attachments(job_id)
            companions = sum(a.kind != "stl" and a.active for a in existing)
            if kind != "stl" and companions >= self.limits.companions:
                raise AppError(
                    f"Можно приложить до {self.limits.companions} сопроводительных файлов",
                    "attachment_limit",
                    413,
                )
            await uow.jobs.attachment(attachment)
            if kind == "stl":
                job.active_stl = attachment.id
                reset_units(job)
            await attached(uow, job, "Файл прикреплён")
            return attachment.model_dump()

        try:
            payload = {"filename": filename, "sha256": digest}
            result = await self.commands.execute(user_id, job_id, request_id, payload, apply)
        except BaseException:
            await self.files.remove(key)
            raise
        if result["id"] != key:
            await self.files.remove(key)
        return result

    async def detach(self, user_id: str, job_id: str, request_id: str, attachment_id: str):
        async def apply(uow: UnitOfWork, job: Job):
            attachments = await uow.jobs.attachments(job_id)
            attachment = next((a for a in attachments if a.id == attachment_id), None)
            if attachment is None:
                raise AppError("Вложение не найдено", "not_found", 404)
            if attachment.active:
                attachment.active = False
                # An unsent upload simply disappears; removing a sent file waits for the next send.
                attachment.draft = not attachment.draft
                await uow.jobs.attachment(attachment)
            if job.active_stl == attachment_id:
                job.active_stl = None
                reset_units(job)
            await attached(uow, job, "Файл убран из задания", any(a.draft for a in attachments))
            return job.model_dump(mode="json")

        payload = {"detach": attachment_id}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)
