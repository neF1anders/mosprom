from __future__ import annotations

from fastapi import APIRouter, Response

from ...services.sessions import SESSION_SECONDS
from ..dependencies import Services, User
from ..schemas import Launch

router = APIRouter(tags=["sessions"])


@router.post("/session/exchange")
async def exchange(body: Launch, response: Response, services: Services):
    token = await services.sessions.exchange(body.token)
    response.set_cookie(
        "mosprom_session", token, httponly=True, samesite="strict", max_age=SESSION_SECONDS
    )
    return {"authenticated": True}


@router.get("/session")
async def session(user: User):
    return {"authenticated": True, "user_id": user}
