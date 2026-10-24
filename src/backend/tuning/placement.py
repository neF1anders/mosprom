"""The model on the table: as loaded, centred in the usable area of the mode.

The orientation is not searched while the STL report has no overhangs by direction, so the only
candidate is the model as loaded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .intake import TuningInput
from .notes import Unmet
from .printer import Mode

ORIENTATION_CANDIDATE = "o1"
ORIENTATION_ASSUMPTION = (
    "ориентация «как загружено» и положение в центре рабочей области стола: нависаний в отчёте "
    "STL нет, поворот не подбирался"
)


@dataclass(frozen=True)
class Placement:
    attachment_id: str
    position: tuple[float, float, float]
    why: str
    assumptions: tuple[str, ...]
    unmet: tuple[Unmet, ...]


def place_model(request: TuningInput, mode: Mode, excluded: Sequence[str | None]) -> Placement:
    """``excluded``: orientation candidates the check ruled out."""
    low, high = mode.usable_x
    height = request.geometry.size[2]
    assumptions = [ORIENTATION_ASSUMPTION]
    unmet = []
    if ORIENTATION_CANDIDATE in excluded:
        unmet.append(Unmet("orientation", "единственный кандидат ориентации исключён этапом 3"))
    if request.quantity > 1:
        assumptions.append(
            f"партия {request.quantity} шт.: в проекте одна модель, копии в раскладку не добавлены"
        )
    if mode.base_diameter is not None:
        assumptions.append(
            f"диаметр основания 5D оставлен по умолчанию ({mode.base_diameter} мм): "
            "диаметр отверстия детали в отчёте STL не передан"
        )
    return Placement(
        attachment_id=request.attachment_id,
        position=(round((low + high) / 2.0, 3), 0.0, round(height / 2.0, 3)),
        why=f"модель стоит как в файле, в центре рабочей области стола режима {mode.label}",
        assumptions=tuple(assumptions),
        unmet=tuple(unmet),
    )
