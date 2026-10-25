from __future__ import annotations

from dataclasses import dataclass, replace

from .geometry import Geometry, Point

AS_LOADED = "o1"
_IDENTITY: tuple[Point, Point, Point] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# порог вертикальности оси
_UPRIGHT = 0.999
# порог симметрии
_SYMMETRIC = 0.9
CLASSIC = "classic"


@dataclass(frozen=True)
class Pose:
    candidate: str
    rotation: tuple[Point, Point, Point]
    size: Point
    why: str
    # нависания в позе
    overhang_fraction: float | None


def pose_for(mode: str, geometry: Geometry) -> Pose:
    loaded = Pose(
        AS_LOADED, _IDENTITY, geometry.size, "модель стоит как в файле", geometry.overhang_fraction
    )
    upright = _axis_upright(geometry)
    if mode == CLASSIC:
        return upright if upright is not None and _stands_better(upright, geometry) else loaded
    if upright is None:
        why = "ось детали в отчёте STL не найдена или не стоит вертикально ни в одном кандидате"
        return replace(loaded, why=f"модель стоит как в файле: {why}")
    return upright


def _stands_better(upright: Pose, geometry: Geometry) -> bool:
    """Лучше ли стоять на торце."""
    symmetric = geometry.revolution or (geometry.symmetry or 0.0) >= _SYMMETRIC
    loaded = next((found for found in geometry.orientations if found.id == AS_LOADED), None)
    lying = geometry.axis is not None and abs(geometry.axis[2]) < _UPRIGHT
    if not (symmetric and lying) or loaded is None:
        return False
    if upright.overhang_fraction is None or loaded.overhang_fraction is None:
        return False
    return upright.overhang_fraction < loaded.overhang_fraction


def _axis_upright(geometry: Geometry) -> Pose | None:
    axis = geometry.axis
    if axis is None:
        return None
    upright = [
        found
        for found in geometry.orientations
        if abs(sum(row * value for row, value in zip(found.rotation[2], axis))) >= _UPRIGHT
    ]
    if not upright:
        return None
    best = min(upright, key=lambda found: (found.overhang_area, -found.bed_contact_area, found.id))
    why = (
        f"ось детали вертикально, торцом на стол (кандидат {best.id}: меньше нависаний, шире опора)"
    )
    return Pose(best.id, best.rotation, best.size, why, best.overhang_fraction)
