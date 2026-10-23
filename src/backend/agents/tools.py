"""Read-only tools agents may call. Every argument is validated; STL analysis is not a tool."""

from __future__ import annotations

import asyncio
import base64
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.errors import AppError
from ..domain.geometry import REPORT_SECTIONS
from ..domain.models import Source
from ..domain.units import convert, plain
from ..ports.operations import Files
from ..services.knowledge import KnowledgeService
from .runner import RunContext

Section = Literal[REPORT_SECTIONS]  # type: ignore[valid-type]
Region = Literal[
    "full",
    "top",
    "bottom",
    "left",
    "right",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
]
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "full": (0, 0, 1, 1),
    "top": (0, 0, 1, 0.5),
    "bottom": (0, 0.5, 1, 1),
    "left": (0, 0, 0.5, 1),
    "right": (0.5, 0, 1, 1),
    "top_left": (0, 0, 0.5, 0.5),
    "top_right": (0.5, 0, 1, 0.5),
    "bottom_left": (0, 0.5, 0.5, 1),
    "bottom_right": (0.5, 0.5, 1, 1),
    "center": (0.25, 0.25, 0.75, 0.75),
}
REQUEST_PIXELS = 2048


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(Args):
    query: str = Field(max_length=500)
    material_id: str | None = None
    property: str | None = None
    conditions: str = ""
    offset: int = Field(default=0, ge=0, le=1000)


class ReportArgs(Args):
    section: Section


class PageArgs(Args):
    source_id: str
    region: Region = "full"


class ConvertArgs(Args):
    value: str
    from_unit: str
    to_unit: str


@dataclass(frozen=True)
class Tool:
    title: str
    description: str
    args: type[Args]
    handler: Callable[[Any, RunContext], Awaitable[dict[str, Any]]]


class ToolBox:
    def __init__(self, knowledge: KnowledgeService, files: Files):
        self.knowledge, self.files = knowledge, files
        self.registry = {
            "search_knowledge": Tool(
                "ищет в базе материалов",
                "Поиск по базе KB-001. В ней только профили материалов Stereotech из STE Slicer "
                "с плотностью и описанием и сведения о профиле принтера Hybrid 530. "
                "Механических и тепловых свойств марок в базе нет. Отсутствие записи не "
                "доказывает непригодность. Цитируй source_id записи.",
                SearchArgs,
                self._search,
            ),
            "read_stl_report": Tool(
                "читает отчёт STL",
                "Раздел полного отчёта анализа STL, уже выполненного кодом. "
                f"Разделы {', '.join(REPORT_SECTIONS)}.",
                ReportArgs,
                self._report,
            ),
            "view_page": Tool(
                "смотрит страницу крупнее",
                "Изображение страницы или фото в полном разрешении либо его области, "
                "когда мелкий текст, таблица или чертёж неразборчивы.",
                PageArgs,
                self._page,
            ),
            "convert_units": Tool(
                "переводит единицы",
                "Точный перевод величины между единицами одной физической природы.",
                ConvertArgs,
                self._convert,
            ),
        }

    def schemas(self, names: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": self.registry[name].description,
                    "parameters": self.registry[name].args.model_json_schema(),
                },
            }
            for name in names
        ]

    def title(self, name: str) -> str:
        return self.registry[name].title

    async def call(self, name: str, arguments: Any, ctx: RunContext) -> dict[str, Any]:
        tool = self.registry[name]
        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as exc:
            raise AppError("Неверные аргументы инструмента", "tool_arguments") from exc
        return await tool.handler(args, ctx)

    async def _search(self, args: SearchArgs, ctx: RunContext) -> dict[str, Any]:
        result = await self.knowledge.search(
            args.query, args.material_id, args.property, args.conditions, args.offset
        )
        for record in result["records"]:
            # Returned records become citable sources for the evidence check.
            source = Source(
                id="kb:" + record["id"],
                ref="kb:" + record["id"],
                kind="knowledge",
                text=f"{record['text']} {record['property']} {record['value']} "
                f"{record.get('unit') or ''}",
            )
            ctx.sources[source.id] = source
            record["source_id"] = source.id
        return result

    async def _report(self, args: ReportArgs, ctx: RunContext) -> dict[str, Any]:
        if ctx.stl_report is None:
            return {"error": "STL не приложен или не проанализирован"}
        return {"section": args.section, "data": ctx.stl_report.get(args.section)}

    async def _page(self, args: PageArgs, ctx: RunContext) -> dict[str, Any]:
        source = ctx.sources.get(args.source_id)
        if source is None or source.image is None:
            return {"error": "У этого источника нет изображения"}
        content = await self.files.read(source.image)
        url = await asyncio.to_thread(crop, content, REGIONS[args.region], REQUEST_PIXELS)
        ctx.images[url] = f"{source.image}#{args.region}"
        label = f"Источник {source.id}, область {args.region}"
        return {
            "status": "Изображение приложено следующим сообщением",
            "images": [
                {"type": "text", "text": label},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }

    async def _convert(self, args: ConvertArgs, ctx: RunContext) -> dict[str, Any]:
        try:
            value = Decimal(args.value.replace(",", "."))
            result = convert(value, args.from_unit, args.to_unit)
        except (InvalidOperation, ValueError) as exc:
            return {"error": str(exc) or "Значение не является числом"}
        return {"value": plain(result), "unit": args.to_unit}


def crop(content: bytes, box: tuple[float, float, float, float], limit: int) -> str:
    from PIL import Image

    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        left, top, right, bottom = box
        part = image.crop(
            (int(left * width), int(top * height), int(right * width), int(bottom * height))
        )
        part.thumbnail((limit, limit))
        buffer = io.BytesIO()
        part.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
