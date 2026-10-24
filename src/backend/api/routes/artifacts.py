from __future__ import annotations

from fastapi import APIRouter, Response

from ..dependencies import Services, User

router = APIRouter(tags=["artifacts"])


@router.get("/jobs/{job_id}/card")
async def card(job_id: str, services: Services, user: User):
    return await services.jobs.current_card(user, job_id)


@router.get("/jobs/{job_id}/artifacts/{artifact_id}")
async def artifact(job_id: str, artifact_id: str, services: Services, user: User):
    data = await services.artifacts.read(user, job_id, artifact_id)
    media = "image/png" if artifact_id.endswith(".png") else "application/octet-stream"
    return Response(
        data,
        media_type=media,
        headers={
            "Content-Disposition": f'inline; filename="{artifact_id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
