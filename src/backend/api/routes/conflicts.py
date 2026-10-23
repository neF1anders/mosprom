from __future__ import annotations

from fastapi import APIRouter

from ..dependencies import Services
from ..schemas import Answers

router = APIRouter(tags=["conflicts"])


@router.post("/jobs/{job_id}/conflicts")
async def resolve(job_id: str, body: Answers, services: Services):
    return await services.answers.answer(
        job_id, str(body.request_id), body.expected_revision, body.answers, conflict=True
    )
