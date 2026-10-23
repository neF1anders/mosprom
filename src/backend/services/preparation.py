from __future__ import annotations

import base64

from ..domain.errors import AppError
from ..domain.models import Attachment, Job
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .runtime import Runtime


class PreparationService:
    def __init__(self, uow: UowFactory, files: Files):
        self.uow, self.files = uow, files

    async def prepare(self, job: Job, runtime: Runtime) -> list[Attachment]:
        async with self.uow() as uow:
            attachments = await uow.jobs.attachments(job.id)
        active = [
            a for a in attachments if a.active and (a.kind != "stl" or a.id == job.active_stl)
        ]
        for attachment in active:
            await runtime.check()
            if attachment.status != "pending":
                continue
            await runtime.event(
                "document.started", f"Проверяю {attachment.filename}", attachment_id=attachment.id
            )
            try:
                result = await self.files.inspect(attachment.id, attachment.kind)
                attachment.fragments = result["fragments"]
                attachment.artifacts = result["artifacts"]
                attachment.status = "completed"
            except AppError as exc:
                attachment.status, attachment.error = "failed", exc.message
            async with self.uow() as uow:
                await uow.jobs.attachment(attachment)
                await uow.commit()
            await runtime.event(
                "document.completed",
                attachment.error or f"Прочитан {attachment.filename}",
                attachment.status,
                attachment_id=attachment.id,
            )
        return active

    async def sources(self, job: Job, attachments: list[Attachment]) -> dict:
        result = {}
        before = None
        while True:
            async with self.uow() as uow:
                messages = await uow.jobs.messages(job.id, before, 100)
            for message in messages:
                if message["role"] == "user":
                    result[message["id"]] = {
                        "text": message["text"],
                        "page": None,
                        "uncertain": False,
                        "revision": message["revision"],
                    }
            if len(messages) < 100:
                break
            before = messages[0]["seq"]
        for attachment in attachments:
            for fragment in attachment.fragments:
                result[f"{attachment.id}:{fragment['page']}"] = {
                    **fragment,
                    "attachment_id": attachment.id,
                    "filename": attachment.filename,
                }
        return result

    async def images(self, sources: dict) -> list[dict]:
        images = []
        for source_id, source in sources.items():
            if not source.get("image"):
                continue
            content = await self.files.read(source["image"])
            images.append(
                {
                    "source_id": source_id,
                    "url": "data:image/png;base64," + base64.b64encode(content).decode(),
                }
            )
        return images
