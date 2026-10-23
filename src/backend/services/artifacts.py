from __future__ import annotations

from ..domain.errors import NotFound
from ..ports.operations import Files
from ..ports.persistence import UowFactory


class ArtifactService:
    def __init__(self, uow: UowFactory, files: Files):
        self.uow, self.files = uow, files

    async def read(self, job_id: str, artifact_id: str) -> bytes:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
            attachments = await uow.jobs.attachments(job_id)
        allowed = {a.id for a in attachments}
        allowed.update(key for a in attachments for key in a.artifacts)
        if job.card and job.card.geometry.report_id:
            allowed.add(job.card.geometry.report_id + ".json")
            allowed.add(job.card.geometry.report_id + ".png")
        if artifact_id not in allowed:
            raise NotFound()
        return await self.files.read(artifact_id)
