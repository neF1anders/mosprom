from __future__ import annotations

from fastapi import APIRouter

from ...domain.model_settings import ModelSettings
from ..dependencies import Services
from ..schemas import ModelEntry

router = APIRouter(tags=["model"])


@router.get("/model")
async def model(services: Services):
    return public(services.model_settings.current())


@router.post("/model")
async def save_model(body: ModelEntry, services: Services):
    return public(services.model_settings.update(body.base_url, body.model, body.api_key))


def public(settings: ModelSettings) -> dict:
    """Ключ не покидает сервер."""
    return {
        "base_url": settings.base_url or None,
        "model": settings.model or None,
        "api_key_set": bool(settings.api_key),
        "configured": settings.configured,
    }
