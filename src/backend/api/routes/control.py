from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from ..dependencies import Services, User
from ..schemas import Command

router = APIRouter(tags=["control"])


@router.post("/jobs/{job_id}/control/{action}")
async def control(
    job_id: str, action: Literal["stop", "retry"], body: Command, services: Services, user: User
):
    return await services.control.run(user, job_id, str(body.request_id), action)
