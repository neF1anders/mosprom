from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from ..dependencies import Services
from ..schemas import Command

router = APIRouter(tags=["control"])


@router.post("/jobs/{job_id}/control/{action}")
async def control(
    job_id: str, action: Literal["stop", "resume", "retry"], body: Command, services: Services
):
    return await services.control.run(job_id, str(body.request_id), action)
