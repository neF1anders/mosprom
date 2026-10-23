from __future__ import annotations

from ..domain.models import Attachment, Geometry
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .commands import fingerprint

ANALYZER_VERSION = "1.2-partial"


class GeometryService:
    def __init__(self, uow: UowFactory, files: Files):
        self.uow, self.files = uow, files

    async def analyze(self, attachment: Attachment, units: str):
        key = fingerprint([attachment.sha256, units, ANALYZER_VERSION, 128])
        async with self.uow() as uow:
            report = await uow.jobs.cache(key)
        cached = report is not None
        if report is None:
            report = await self.files.analyze(attachment.id, units, key)
            async with self.uow() as uow:
                await uow.jobs.cache_put(key, report)
                await uow.commit()
        defects = list(report.get("validation", {}).get("defects", []))
        if report.get("topology", {}).get("component_count", 0) > 1:
            defects.append("multiple_shells")
        geometry = Geometry(
            readable="geometry" in report,
            units=units,
            coordinate_unit="unknown" if units == "unknown" else "mm",
            extents=report.get("geometry", {}).get("extents", []),
            defects=defects,
            physical_volume_confirmed=False,
            report_id=key,
            preview_id=report.get("preview"),
            limitations=report.get("warnings", [])
            + [f"Не завершена проверка {k}" for k in report.get("partial_errors", {})],
        )
        return geometry, report, cached
