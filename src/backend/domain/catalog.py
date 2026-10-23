"""Versioned, executable prerequisites. All predicates are pure domain rules."""

from dataclasses import dataclass
from typing import Callable

from .models import TaskCard

RULES_VERSION = "2"


@dataclass(frozen=True)
class Gate:
    id: str
    action: str
    satisfied: Callable[[TaskCard], bool]
    reason: str


GATES = (
    Gate(
        "GEO-001",
        "select_parameters",
        lambda c: c.geometry.readable,
        "Нужна читаемая геометрия STL",
    ),
    Gate(
        "REQ-001",
        "select_parameters",
        lambda c: all(r.verified or not r.mandatory for r in c.requirements),
        "Есть непроверенные обязательные требования",
    ),
    Gate(
        "GCODE-001",
        "prepare_gcode",
        lambda c: False,
        "Подготовка G-code требует результатов следующих этапов",
    ),
)
