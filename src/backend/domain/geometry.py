"""Server-owned STL facts: report binding and the compact summary agents receive."""

from __future__ import annotations

from typing import Any

from .errors import AppError
from .models import Attachment, Geometry, StlAnalysis

REPORT_SECTIONS = (
    "file",
    "units",
    "preprocessing",
    "validation",
    "topology",
    "geometry",
    "sections",
    "normal_chords",
    "warnings",
    "partial_errors",
)
SECTION_FIELDS = ("axis", "fraction_of_bounds", "closed_contour_count", "open_entity_count")


def bind_analysis(attachment: Attachment, units: str, report: dict[str, Any]) -> StlAnalysis:
    file, measured = report.get("file"), report.get("units")
    if not isinstance(file, dict) or not isinstance(measured, dict):
        raise AppError("Некорректные метаданные отчёта STL", "stale_analysis", 503)
    if file.get("sha256") != attachment.sha256 or measured.get("input_unit") != units:
        raise AppError("Отчёт STL не соответствует файлу или единицам", "stale_analysis", 503)
    return StlAnalysis(attachment_id=attachment.id, sha256=attachment.sha256, report=report)


def summarize(report: dict[str, Any], units: str, report_id: str) -> Geometry:
    geometry = report.get("geometry", {})
    topology = report.get("topology", {})
    defects = list(report.get("validation", {}).get("defects", []))
    if topology.get("component_count", 0) > 1:
        defects.append("multiple_shells")
    chords = report.get("normal_chords", {})
    return Geometry(
        readable="extents" in geometry,
        units=units,
        extents=geometry.get("extents", []),
        watertight=topology.get("watertight"),
        components=topology.get("component_count"),
        defects=defects,
        surface_area=geometry.get("surface_area"),
        volume=geometry.get("volume"),
        volume_basis=geometry.get("volume_basis", ""),
        min_wall_sample=chords.get("minimum_sampled"),
        sections=[{k: s[k] for k in SECTION_FIELDS if k in s} for s in report.get("sections", [])],
        limitations=[*report.get("warnings", []), *_partial(report)],
        report_id=report_id,
        preview_id=report.get("preview"),
    )


def _partial(report: dict[str, Any]) -> list[str]:
    # Sorted: JSONB does not keep key order, and the summary is part of agent cache keys.
    return [f"Не завершена проверка {name}" for name in sorted(report.get("partial_errors", {}))]
