from __future__ import annotations

from fastapi import APIRouter, Query

from ..dependencies import Services, User
from ..schemas import Command, CreateJob, RenameJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201)
async def create(body: CreateJob, services: Services, user: User):
    return await services.jobs.create(user, str(body.request_id), body.title)


@router.get("")
async def list_jobs(services: Services, user: User, before: str | None = None):
    return await services.jobs.list(user, before)


@router.post("/{job_id}/rename")
async def rename(job_id: str, body: RenameJob, services: Services, user: User):
    return await services.jobs.rename(user, job_id, str(body.request_id), body.title)


@router.post("/{job_id}/delete")
async def delete(job_id: str, body: Command, services: Services, user: User):
    return await services.jobs.delete(user, job_id, str(body.request_id))


@router.get("/{job_id}")
async def snapshot(
    job_id: str,
    services: Services,
    user: User,
    before: int | None = Query(default=None, ge=1),
):
    return await services.jobs.snapshot(user, job_id, before)
