"""Values the selection steps hand on: settings, unmet requirements, applied constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

EPSILON = 1e-9


@dataclass(frozen=True)
class Unmet:
    """A requirement or a check constraint the parameter set does not meet."""

    requirement_id: str
    why: str
    conflicts_with: str | None = None


@dataclass(frozen=True)
class ConstraintResult:
    """How one constraint of the check was applied on the second pass."""

    id: str
    result: Literal["applied", "not_applied"]
    why: str


@dataclass(frozen=True)
class SettingChoice:
    """A setting sent to the slicer, with why and where its value comes from."""

    value: Any
    why: str
    source: str
    unit: str | None = None
    scope: str | None = None
