"""Files and the STL by code: documents parsed in separate processes, analysis cached by content."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..domain.errors import AppError
from ..domain.geometry import bind_analysis, summarize
from ..domain.hashing import fingerprint
from ..domain.models import DOCUMENT_VERSION, Attachment, Geometry, Job, StlAnalysis
from ..ports.operations import Files
from .concurrency import together
from .runner import RunContext
from .store import RunStore

ANALYZER_VERSION = "1.2-partial"
# STL has no units; like Cura, the file is read in millimetres and nobody is asked.
UNITS = "mm"


@dataclass(frozen=True)
class StlFacts:
    attachment: Attachment
    report: dict[str, Any]
    analysis: StlAnalysis
    geometry: Geometry


class Sources:
    def __init__(self, store: RunStore, files: Files):
        self.store, self.files = store, files

    async def parse(self, attachments: list[Attachment], ctx: RunContext) -> None:
        """Documents are parsed side by side; a file that failed before is tried again.

        Parsing is silent: the gate reads the documents before it decides to start, and a
        plain chat reply must not open the timeline.
        """
        await together(
            *(self._parse(a, ctx) for a in attachments if a.kind != "stl" and _outdated(a))
        )

    async def announce(self, attachments: list[Attachment], ctx: RunContext) -> None:
        await ctx.event("files.started", "Читаю файлы")
        broken = [a.filename for a in attachments if a.status == "failed" and a.kind != "stl"]
        await ctx.event(
            "files.failed" if broken else "files.completed",
            "Не все файлы прочитаны" if broken else "Файлы прочитаны",
            "failed" if broken else "completed",
            failed=broken,
        )

    async def _parse(self, attachment: Attachment, ctx: RunContext) -> None:
        await ctx.check()
        try:
            result = await self.files.inspect(attachment.id, attachment.kind)
            attachment.fragments, attachment.artifacts = result["fragments"], result["artifacts"]
            attachment.status, attachment.error = "completed", None
            attachment.parser_version = DOCUMENT_VERSION
        except AppError as exc:
            attachment.status, attachment.error = "failed", exc.message
        await self.store.save(attachment)

    async def stl(
        self,
        job: Job,
        attachments: list[Attachment],
        ctx: RunContext,
        ready: Callable[[StlFacts], Awaitable[None]] | None = None,
    ) -> StlFacts | None:
        """``ready`` runs before the completion event, so the interface sees its effect."""
        attachment = next((a for a in attachments if a.id == job.active_stl), None)
        if attachment is None:
            return None
        await ctx.event("stl.started", "Анализирую STL")
        key = fingerprint([attachment.sha256, UNITS, ANALYZER_VERSION, 128])
        try:
            report = await self.store.cached(key)
            if report is None:
                report = await self.files.analyze(attachment.id, UNITS, key)
                # A checkpoint cut by the time limit is not the final word on this file.
                if report.get("status") != "partial":
                    await self.store.cache(key, report)
            analysis = bind_analysis(attachment, UNITS, report)
        except AppError as exc:
            attachment.status, attachment.error = "failed", exc.message
            await self.store.save(attachment)
            await ctx.event("stl.failed", exc.message, "failed")
            return None
        geometry = summarize(report, UNITS, key)
        attachment.status, attachment.error = "completed", None
        attachment.artifacts = list(
            dict.fromkeys(
                [*attachment.artifacts, key + ".json", *filter(None, [geometry.preview_id])]
            )
        )
        await self.store.save(attachment)
        facts = StlFacts(attachment, report, analysis, geometry)
        if ready is not None:
            await ready(facts)
        status = "warning" if geometry.defects else "completed"
        await ctx.event(
            "stl.completed", "STL проанализирован", status, geometry=geometry.model_dump()
        )
        return facts


def _outdated(attachment: Attachment) -> bool:
    return attachment.status in {"pending", "failed"} or (
        attachment.status == "completed" and attachment.parser_version != DOCUMENT_VERSION
    )
