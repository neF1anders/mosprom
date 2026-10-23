from __future__ import annotations

from fastapi import APIRouter, Response

from ..dependencies import Services
from ..schemas import Launch

router = APIRouter(tags=["sessions"])


@router.post("/session/exchange")
async def exchange(body: Launch, response: Response, services: Services):
    token = await services.sessions.exchange(body.token)
    response.set_cookie(
        "mosprom_session", token, httponly=True, samesite="strict", max_age=30 * 86400
    )
    return {"authenticated": True}


@router.get("/session")
async def session():
    return {"authenticated": True}
