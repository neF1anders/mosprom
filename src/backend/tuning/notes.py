from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

EPSILON = 1e-9


@dataclass(frozen=True)
class Unmet:
    """Невыполненное требование или ограничение проверки."""

    requirement_id: str
    why: str
    conflicts_with: str | None = None


@dataclass(frozen=True)
class ConstraintResult:
    """Результат применения одного ограничения."""

    id: str
    result: Literal["applied", "not_applied"]
    why: str


@dataclass(frozen=True)
class SettingChoice:
    """Настройка слайсера с причиной."""

    value: Any
    why: str
    source: str
    unit: str | None = None
    scope: str | None = None
