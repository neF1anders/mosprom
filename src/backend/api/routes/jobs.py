from __future__ import annotations

from fastapi import APIRouter, Query

from ..dependencies import Services
from ..schemas import CreateJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201)
async def create(body: CreateJob, services: Services):
    return await services.jobs.create(str(body.request_id), body.title)


@router.get("")
async def list_jobs(services: Services, before: str | None = None):
    return await services.jobs.list(before)


@router.get("/{job_id}")
async def snapshot(job_id: str, services: Services, before: int | None = Query(default=None, ge=1)):
    return await services.jobs.snapshot(job_id, before)
