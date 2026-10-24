"""The model on the table: as loaded, centred in the usable area of the mode.

The orientation is not searched yet: the overhang share of the STL report is measured for the
model as loaded, which stays the only candidate. In 5D the cylinder the slicer prints around
follows the bore of the part when the report gives one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .intake import TuningInput
from .notes import SettingChoice, Unmet
from .printer import BASE_DIAMETER_KEY, Mode

ORIENTATION_CANDIDATE = "o1"
# Without and with the overhang share in the STL report.
ORIENTATION_ASSUMPTION = (
    "ориентация «как загружено» и положение в центре рабочей области стола: нависаний в отчёте "
    "STL нет, поворот не подбирался"
)
ORIENTATION_WITH_OVERHANGS = (
    "ориентация «как загружено» и положение в центре рабочей области стола, поворот пока "
    "не подбирается"
)
BASE_DIAMETER_SOURCE = "assumption:stl.revolution.bore"


@dataclass(frozen=True)
class Placement:
    attachment_id: str
    position: tuple[float, float, float]
    why: str
    # The assumption the placed model cites as its source.
    orientation_assumption: str
    assumptions: tuple[str, ...]
    unmet: tuple[Unmet, ...]
    # The 5D base diameter taken from the bore of the part.
    settings: Mapping[str, SettingChoice]


def place_model(request: TuningInput, mode: Mode, excluded: Sequence[str | None]) -> Placement:
    """``excluded``: orientation candidates the check ruled out."""
    low, high = mode.usable_x
    height = request.geometry.size[2]
    orientation = ORIENTATION_ASSUMPTION
    if request.geometry.overhang_fraction is not None:
        orientation = ORIENTATION_WITH_OVERHANGS
    assumptions = [orientation]
    unmet = []
    if ORIENTATION_CANDIDATE in excluded:
        unmet.append(Unmet("orientation", "единственный кандидат ориентации исключён этапом 3"))
    if request.quantity > 1:
        assumptions.append(
            f"партия {request.quantity} шт.: в проекте одна модель, копии в раскладку не добавлены"
        )
    settings, base_assumptions = _base_diameter(request.geometry.bore_diameter, mode)
    return Placement(
        attachment_id=request.attachment_id,
        position=(round((low + high) / 2.0, 3), 0.0, round(height / 2.0, 3)),
        why=f"модель стоит как в файле, в центре рабочей области стола режима {mode.label}",
        orientation_assumption=orientation,
        assumptions=(*assumptions, *base_assumptions),
        unmet=tuple(unmet),
        settings=settings,
    )


def _base_diameter(bore: float | None, mode: Mode) -> tuple[dict[str, SettingChoice], list[str]]:
    """The bore rounded down to 0.5 mm; the build default without a bore or below its minimum."""
    if mode.base_diameter is None:
        return {}, []
    kept = f"диаметр основания 5D оставлен по умолчанию ({mode.base_diameter} мм)"
    if bore is None:
        return {}, [f"{kept}: диаметр отверстия детали в отчёте STL не передан"]
    base = math.floor(bore * 2) / 2
    if base < mode.base_diameter_min:
        return {}, [
            f"{kept}, отверстие детали {bore:g} мм меньше допустимого минимума "
            f"{mode.base_diameter_min:g} мм"
        ]
    why = f"диаметр отверстия детали {bore:g} мм по отчёту STL с округлением вниз до 0.5 мм"
    return {BASE_DIAMETER_KEY: SettingChoice(base, why, BASE_DIAMETER_SOURCE, "mm")}, []
