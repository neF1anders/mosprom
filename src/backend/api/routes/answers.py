from __future__ import annotations

from fastapi import APIRouter

from ..dependencies import Services, User
from ..schemas import Answers

router = APIRouter(tags=["answers"])


@router.post("/jobs/{job_id}/answers")
async def answer(job_id: str, body: Answers, services: Services, user: User):
    return await services.answers.answer(
        user, job_id, str(body.request_id), body.expected_revision, body.answers
    )
