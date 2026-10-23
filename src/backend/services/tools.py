from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.errors import AppError
from ..domain.models import Attachment, Job
from .geometry import GeometryService
from .knowledge import KnowledgeService


class AnalyzeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: str
    units: Literal["unknown", "mm", "cm", "m", "inch"] = "unknown"


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(max_length=500)
    material_id: str | None = None
    property: str | None = None
    conditions: str = ""
    offset: int = Field(default=0, ge=0, le=1000)


TOOL_DEFINITIONS: list[tuple[str, str, type[BaseModel]]] = [
    ("analyze_stl", "Analyze active STL without repair using confirmed units", AnalyzeArgs),
    ("search_knowledge", "Search local KB-001; missing evidence is not rejection", SearchArgs),
]

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": model.model_json_schema(),
        },
    }
    for name, description, model in TOOL_DEFINITIONS
]


class ToolService:
    def __init__(self, geometry: GeometryService, knowledge: KnowledgeService):
        self.geometry, self.knowledge = geometry, knowledge

    async def call(self, name: str, arguments: str, job: Job, attachments: list[Attachment]):
        handlers = {"analyze_stl": self._analyze, "search_knowledge": self._search}
        if name not in handlers:
            raise AppError("Неизвестный инструмент", "unknown_tool")
        try:
            return await handlers[name](json.loads(arguments), job, attachments)
        except (ValueError, ValidationError, TypeError) as exc:
            raise AppError("Неверные аргументы инструмента", "tool_arguments") from exc

    async def _analyze(self, arguments: dict, job: Job, attachments: list[Attachment]):
        args = AnalyzeArgs.model_validate(arguments)
        attached = {a.id: a for a in attachments if a.active and a.job_id == job.id}
        if args.attachment_id != job.active_stl or args.attachment_id not in attached:
            raise AppError(
                "Инструменту доступен только активный STL этого задания", "foreign_attachment"
            )
        if args.units != job.units:
            raise AppError("Масштаб должен быть подтверждён пользователем", "unconfirmed_units")
        geometry, _, cached = await self.geometry.analyze(attached[args.attachment_id], args.units)
        return {"geometry": geometry.model_dump(), "cached": cached}

    async def _search(self, arguments: dict, job: Job, attachments: list[Attachment]):
        args = SearchArgs.model_validate(arguments)
        return await self.knowledge.search(
            args.query, args.material_id, args.property, args.conditions, args.offset
        )
