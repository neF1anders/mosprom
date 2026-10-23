from __future__ import annotations

from fastapi import APIRouter

from ..dependencies import Services, User
from ..schemas import SendMessage

router = APIRouter(tags=["messages"])


@router.post("/jobs/{job_id}/messages")
async def send(job_id: str, body: SendMessage, services: Services, user: User):
    return await services.messages.send(user, job_id, str(body.request_id), body.text)
