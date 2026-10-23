from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Form, UploadFile

from ..dependencies import Services, User
from ..schemas import Command

router = APIRouter(tags=["attachments"])


@router.post("/jobs/{job_id}/attachments", status_code=201)
async def upload(
    job_id: str, file: UploadFile, services: Services, user: User, request_id: UUID = Form()
):
    async def chunks():
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        return await services.uploads.upload(
            user, job_id, str(request_id), file.filename or "file", chunks()
        )
    finally:
        await file.close()


@router.post("/jobs/{job_id}/attachments/{attachment_id}/detach")
async def detach(job_id: str, attachment_id: str, body: Command, services: Services, user: User):
    return await services.uploads.detach(user, job_id, str(body.request_id), attachment_id)
