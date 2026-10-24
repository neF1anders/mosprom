"""The model on the table: in the pose of its mode (``orientation.py``), centred in the usable
area of the mode.

In 5D the cylinder the slicer prints around follows the through bore of the part when the part
is symmetric around that bore (a body of revolution, or an impeller whose blades break the round
sections but not the symmetry).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .geometry import Geometry
from .intake import TuningInput
from .notes import SettingChoice, Unmet
from .orientation import AS_LOADED, Pose
from .printer import BASE_DIAMETER_KEY, Mode

# Without and with the overhang share in the STL report.
ORIENTATION_ASSUMPTION = (
    "ориентация «как загружено» и положение в центре рабочей области стола: нависаний в отчёте "
    "STL нет, поворот не подбирался"
)
ORIENTATION_WITH_OVERHANGS = (
    "ориентация «как загружено» и положение в центре рабочей области стола, поворот в 3D "
    "не подбирается"
)
BASE_DIAMETER_SOURCE = "assumption:stl.revolution.bore"
# Symmetry of the part around its axis from which the bore is taken as the axis of 5D.
_SYMMETRIC = 0.9


@dataclass(frozen=True)
class Placement:
    attachment_id: str
    candidate: str
    rotation: tuple[tuple[float, float, float], ...]
    position: tuple[float, float, float]
    why: str
    # The assumption the placed model cites as its source.
    orientation_assumption: str
    assumptions: tuple[str, ...]
    unmet: tuple[Unmet, ...]
    # The 5D base diameter taken from the bore of the part.
    settings: Mapping[str, SettingChoice]


def place_model(
    request: TuningInput, mode: Mode, pose: Pose, excluded: Sequence[str | None]
) -> Placement:
    """``excluded``: orientation candidates the check ruled out."""
    low, high = mode.usable_x
    height = pose.size[2]
    orientation = ORIENTATION_ASSUMPTION
    if request.geometry.overhang_fraction is not None:
        orientation = ORIENTATION_WITH_OVERHANGS
    if pose.candidate != AS_LOADED:
        orientation = f"{pose.why}; положение в центре рабочей области стола"
    assumptions = [orientation]
    unmet = []
    if pose.candidate in excluded:
        unmet.append(
            Unmet("orientation", f"кандидат ориентации {pose.candidate} исключён этапом 3")
        )
    if request.quantity > 1:
        assumptions.append(
            f"партия {request.quantity} шт.: в проекте одна модель, копии в раскладку не добавлены"
        )
    settings, base_assumptions = _base_diameter(request.geometry, mode)
    return Placement(
        attachment_id=request.attachment_id,
        candidate=pose.candidate,
        rotation=pose.rotation,
        position=(round((low + high) / 2.0, 3), 0.0, round(height / 2.0, 3)),
        why=f"{pose.why}, в центре рабочей области стола режима {mode.label}",
        orientation_assumption=orientation,
        assumptions=(*assumptions, *base_assumptions),
        unmet=tuple(unmet),
        settings=settings,
    )


def _base_diameter(geometry: Geometry, mode: Mode) -> tuple[dict[str, SettingChoice], list[str]]:
    """The through bore of a body of revolution rounded down to 0.5 mm; the build default
    without one or below its minimum."""
    if mode.base_diameter is None:
        return {}, []
    kept = f"диаметр основания 5D оставлен по умолчанию ({mode.base_diameter} мм)"
    bore = geometry.bore_diameter
    if bore is None:
        return {}, [f"{kept}: диаметр отверстия детали в отчёте STL не передан"]
    # The base cylinder runs through the part along its axis.
    if not geometry.revolution and (geometry.symmetry or 0.0) < _SYMMETRIC:
        return {}, [f"{kept}, деталь по отчёту STL не симметрична вокруг оси отверстия"]
    if not geometry.bore_through:
        return {}, [f"{kept}, отверстие детали {bore:g} мм по отчёту STL не сквозное"]
    base = math.floor(bore * 2) / 2
    if base < mode.base_diameter_min:
        return {}, [
            f"{kept}, отверстие детали {bore:g} мм меньше допустимого минимума "
            f"{mode.base_diameter_min:g} мм"
        ]
    why = f"диаметр отверстия детали {bore:g} мм по отчёту STL с округлением вниз до 0.5 мм"
    return {BASE_DIAMETER_KEY: SettingChoice(base, why, BASE_DIAMETER_SOURCE, "mm")}, []
