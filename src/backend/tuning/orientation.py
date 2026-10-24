"""How the part stands on the table in a printing mode.

In 5D the slicer prints around a vertical axis, so the part's own axis must stand vertical: of
the report's candidates that do this, the one with the least overhang, then the widest contact,
is taken. In 3D a part symmetric around its axis (gear, wheel, fan, boot) also stands on its end
face when that gives fewer overhangs than the file: both teams with finished 3MF projects of the
case put these parts so, and the Stereotech memo prints a gear with its teeth in the table
plane. Any other part stays as loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .geometry import Geometry, Point

AS_LOADED = "o1"
_IDENTITY: tuple[Point, Point, Point] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# |cos| of the angle between the turned axis and the vertical: within about 2.5 degrees.
_UPRIGHT = 0.999
# Symmetry around the axis from which a part counts as one to stand on its end face.
_SYMMETRIC = 0.9
CLASSIC = "classic"


@dataclass(frozen=True)
class Pose:
    candidate: str
    rotation: tuple[Point, Point, Point]
    size: Point
    why: str
    # Overhang share in this pose; None when the report does not measure it.
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
    """A symmetric part lying on its side, on its end face with fewer overhangs than as loaded.

    A part already standing on an end face is not turned over: a flip changes little and moves
    away from the file.
    """
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
