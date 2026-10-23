from __future__ import annotations

from fastapi import APIRouter

from ...domain.models import CARD_SCHEMA_VERSION
from ..dependencies import Services

router = APIRouter(tags=["diagnostics"])


@router.get("/health")
async def health():
    return {"status": "ok", "schema_version": "1.0"}


@router.get("/capabilities")
async def capabilities(services: Services):
    return {
        "card_schema_version": CARD_SCHEMA_VERSION,
        "formats": ["stl", "pdf", "docx", "txt", "md", "jpg", "png"],
        "knowledge_scope": "KB-001",
        "model_configured": bool(services.settings.qwen_api_key),
        "stage2_connected": bool(services.settings.handoff_url),
        "web_search": False,
        "events": "sse",
    }
