from __future__ import annotations

from fastapi import APIRouter

from ...config import Settings
from ...domain.models import CARD_SCHEMA_VERSION
from ..dependencies import Services

router = APIRouter(tags=["diagnostics"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/capabilities")
async def capabilities(services: Services):
    settings = services.settings
    return {
        "card_schema_version": CARD_SCHEMA_VERSION,
        "formats": ["stl", "pdf", "docx", "txt", "md", "jpg", "jpeg", "png"],
        "knowledge_scope": "KB-001",
        "model_configured": services.model_settings.current().configured,
        "events": "sse",
        "project_folder": project_folder(settings),
    }


def project_folder(settings: Settings) -> str | None:
    """Where the slicer saves projects, as the user's computer names it, when it is known."""
    if settings.slicer_host_folder:
        return settings.slicer_host_folder
    return str(settings.slicer_folder) if settings.slicer_folder.is_dir() else None
