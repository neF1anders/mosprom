"""The STL analysis report of the card (``stl_analysis.report``) -> the model geometry.

Only the fields of ``src/mesh_analysis.py`` that parameter selection reads are parsed. The
report has no overhang measurement, so the rules that depend on overhangs do not fire; the
user is told so through an assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.errors import AppError
from ..domain.models import StlAnalysis

_DIGITS = 3
Point = tuple[float, float, float]


class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _File(_Part):
    sha256: str | None = None


class _Units(_Part):
    coordinate_unit: str = "unknown"


class _Measures(_Part):
    bounds: tuple[Point, Point] | None = None
    volume: float | None = None
    surface_area: float | None = None


class _Component(_Part):
    signed_volume: float | None = None


class _Topology(_Part):
    watertight: bool = False
    winding_consistent: bool = False
    components: list[_Component] = Field(default_factory=list)


class _Validation(_Part):
    defects: list[str] = Field(default_factory=list)


class _Chords(_Part):
    minimum_sampled: float | None = None


class _Report(_Part):
    file: _File = _File()
    units: _Units = _Units()
    geometry: _Measures = _Measures()
    topology: _Topology = _Topology()
    validation: _Validation = _Validation()
    normal_chords: _Chords = _Chords()
    warnings: list[str] = Field(default_factory=list)
    partial_errors: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class Geometry:
    """Bounding box size in millimetres and the measures rules can read as facts."""

    size: Point
    needs_repair: bool
    volume: float | None = None
    surface_area: float | None = None
    # Shortest sampled inward chord: an estimate that can miss thin features.
    min_wall_estimate: float | None = None


@dataclass(frozen=True)
class GeometryReading:
    attachment_id: str
    geometry: Geometry
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]


def read_geometry(analysis: StlAnalysis | None) -> GeometryReading:
    if analysis is None or not analysis.report:
        raise AppError(
            "В карточке нет отчёта STL, без геометрии модели параметры не подобрать",
            "stl_report_missing",
        )
    report = _parse(analysis.report)
    if report.file.sha256 and report.file.sha256 != analysis.sha256:
        raise AppError("Отчёт STL относится к другому файлу модели", "stl_report_mismatch")
    assumptions = (
        _unit_assumption(report.units.coordinate_unit),
        "доли нависаний нет в отчёте STL этапа 1: поддержки по геометрии не включаются",
    )
    if report.geometry.bounds is None:
        raise AppError("В отчёте STL нет габаритов модели", "stl_report_bounds")
    low, high = report.geometry.bounds
    geometry = Geometry(
        size=(_rounded(high[0] - low[0]), _rounded(high[1] - low[1]), _rounded(high[2] - low[2])),
        needs_repair=_needs_repair(report),
        volume=_optional(report.geometry.volume),
        surface_area=_optional(report.geometry.surface_area),
        min_wall_estimate=_optional(report.normal_chords.minimum_sampled),
    )
    warnings = [f"stl report: {text}" for text in report.warnings]
    warnings.extend(
        f"stl report partial error: {part} ({error})"
        for part, error in report.partial_errors.items()
    )
    return GeometryReading(analysis.attachment_id, geometry, assumptions, tuple(warnings))


def _parse(report: dict[str, Any]) -> _Report:
    try:
        return _Report.model_validate(report)
    except ValidationError as error:
        raise AppError("Отчёт STL в карточке не читается", "stl_report_invalid") from error


def _unit_assumption(unit: str) -> str:
    if unit == "mm":
        return "координаты модели в миллиметрах (подтверждено этапом 1)"
    if unit == "unknown":
        return "единицы STL неизвестны: координаты приняты за миллиметры"
    raise AppError(f"Единицы координат STL {unit} не поддерживаются", "stl_report_units")


def _needs_repair(report: _Report) -> bool:
    topology = report.topology
    negative = any((part.signed_volume or 0.0) < 0 for part in topology.components)
    closed = topology.watertight and topology.winding_consistent
    return not closed or negative or bool(report.validation.defects)


def _rounded(value: float) -> float:
    return round(float(value), _DIGITS)


def _optional(value: float | None) -> float | None:
    return None if value is None else _rounded(value)
