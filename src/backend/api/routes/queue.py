from __future__ import annotations

from fastapi import APIRouter

from ..dependencies import Services, User
from ..schemas import Command, SendMessage

router = APIRouter(prefix="/jobs/{job_id}/queue", tags=["queue"])


@router.post("")
async def add(job_id: str, body: SendMessage, services: Services, user: User):
    return await services.queued.add(user, job_id, str(body.request_id), body.text)


@router.post("/{item_id}/edit")
async def edit(job_id: str, item_id: str, body: SendMessage, services: Services, user: User):
    return await services.queued.edit(user, job_id, str(body.request_id), item_id, body.text)


@router.post("/{item_id}/delete")
async def delete(job_id: str, item_id: str, body: Command, services: Services, user: User):
    return await services.queued.delete(user, job_id, str(body.request_id), item_id)


@router.post("/{item_id}/send")
async def send(job_id: str, item_id: str, body: Command, services: Services, user: User):
    return await services.queued.send(user, job_id, str(body.request_id), item_id)
