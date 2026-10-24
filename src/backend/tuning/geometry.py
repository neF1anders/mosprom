"""The STL analysis report of the card (``stl_analysis.report``) -> the model geometry.

Only the fields of ``src/mesh_analysis.py`` that parameter selection reads are parsed, with the
optional sections of the stage-one contract: the overhang share (``overhangs``) and the bore of
a body of revolution (``revolution``). A report without the overhang share leaves the rules
that depend on overhangs silent; the user is told so through an assumption.
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


class _Overhangs(_Part):
    area_fraction: float | None = None


class _Bore(_Part):
    through: bool = False
    diameter_mm: float | None = None


class _Revolution(_Part):
    is_revolution: bool = False
    axis_direction: Point | None = None
    symmetry_score: float | None = None
    outer_diameter_mm: float | None = None
    length_along_axis_mm: float | None = None
    bore: _Bore | None = None


class _Orientation(_Part):
    id: str
    rotation: tuple[Point, Point, Point]
    overhang_area_mm2: float | None = None
    overhang_area_fraction: float | None = None
    bed_contact_area_mm2: float | None = None
    extents_mm: Point | None = None


class _Report(_Part):
    file: _File = _File()
    units: _Units = _Units()
    geometry: _Measures = _Measures()
    warnings: list[str] = Field(default_factory=list)
    partial_errors: dict[str, str] = Field(default_factory=dict)
    overhangs: _Overhangs | None = None
    revolution: _Revolution | None = None
    orientations: list[_Orientation] = Field(default_factory=list)


@dataclass(frozen=True)
class Orientation:
    """A bed orientation the STL report measured: its rotation and what it puts on the table."""

    id: str
    rotation: tuple[Point, Point, Point]
    size: Point
    overhang_area: float
    overhang_fraction: float | None
    bed_contact_area: float


@dataclass(frozen=True)
class Geometry:
    """Bounding box size in millimetres and the measures selection reads."""

    size: Point
    # Share of the surface overhanging past 45 degrees, the model as loaded.
    overhang_fraction: float | None = None
    # The coaxial bore: smallest diameter, whether it runs through and whether the part is a
    # body of revolution around it.
    bore_diameter: float | None = None
    bore_through: bool = False
    revolution: bool = False
    # The axis the round sections are measured around, and how alike the part is around it.
    axis: Point | None = None
    symmetry: float | None = None
    # Length along the axis over the outer diameter: a flat disc is well below 0.3.
    length_to_diameter: float | None = None
    orientations: tuple[Orientation, ...] = ()

    @property
    def slenderness(self) -> float:
        """Height over the narrower side of the footprint: a tall thin part may tip over."""
        width, depth, height = self.size
        return height / min(width, depth) if min(width, depth) > 0 else 0.0


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
    assumptions = [_unit_assumption(report.units.coordinate_unit)]
    if report.geometry.bounds is None:
        raise AppError("В отчёте STL нет габаритов модели", "stl_report_bounds")
    low, high = report.geometry.bounds
    revolution = report.revolution or _Revolution()
    bore = revolution.bore or _Bore()
    geometry = Geometry(
        size=(_rounded(high[0] - low[0]), _rounded(high[1] - low[1]), _rounded(high[2] - low[2])),
        overhang_fraction=_overhang_fraction(report),
        bore_diameter=_optional(bore.diameter_mm),
        bore_through=bore.through,
        revolution=revolution.is_revolution,
        axis=revolution.axis_direction,
        symmetry=revolution.symmetry_score,
        length_to_diameter=_ratio(revolution.length_along_axis_mm, revolution.outer_diameter_mm),
        orientations=tuple(
            _orientation(found, size) for found in report.orientations if (size := found.extents_mm)
        ),
    )
    if geometry.overhang_fraction is None:
        assumptions.append(
            "доли нависаний нет в отчёте STL этапа 1: поддержки по геометрии не включаются"
        )
    warnings = [f"stl report: {text}" for text in report.warnings]
    warnings.extend(
        f"stl report partial error: {part} ({error})"
        for part, error in report.partial_errors.items()
    )
    return GeometryReading(analysis.attachment_id, geometry, tuple(assumptions), tuple(warnings))


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


def _overhang_fraction(report: _Report) -> float | None:
    """Not rounded: the rules compare it with a threshold of 0.05."""
    return None if report.overhangs is None else report.overhangs.area_fraction


def _orientation(found: _Orientation, size: Point) -> Orientation:
    return Orientation(
        id=found.id,
        rotation=found.rotation,
        size=size,
        overhang_area=found.overhang_area_mm2 or 0.0,
        overhang_fraction=found.overhang_area_fraction,
        bed_contact_area=found.bed_contact_area_mm2 or 0.0,
    )


def _ratio(length: float | None, diameter: float | None) -> float | None:
    if length is None or not diameter:
        return None
    return round(length / diameter, _DIGITS)


def _rounded(value: float) -> float:
    return round(float(value), _DIGITS)


def _optional(value: float | None) -> float | None:
    return None if value is None else _rounded(value)
