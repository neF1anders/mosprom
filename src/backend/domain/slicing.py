from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import Value
from .parameters import Feedback


class SlicerCall(Value):
    """Один вызов инструмента MCP."""

    step: str
    tool: str
    args: dict[str, Any]


class Unsupported(Value):
    step: str
    reason: str


class Clamped(Value):
    """Значение, записанное слайсером иначе."""

    key: str
    requested: Any
    written: Any


class CallOutcome(Value):
    step: str
    tool: str
    ok: bool
    error: str | None = None


class SliceReport(Value):
    """Отчёт о нарезке слайсером."""

    status: Literal["sliced", "failed", "unavailable"]
    message: str
    steps: list[CallOutcome] = Field(default_factory=list)
    clamped: list[Clamped] = Field(default_factory=list)
    unsupported: list[Unsupported] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # копии и папка
    gcode: str | None = None
    project: str | None = None
    folder: str | None = None
    print_time_seconds: int | None = None
    material_grams: float | None = None
    material_meters: float | None = None


class GcodeFinding(Value):
    """Находка проверки файла G-code."""

    id: str
    kind: Literal["file", "apply", "content"]
    level: Literal["error", "warning", "info"]
    message: str
    key: str | None = None


class GcodeCheck(Value):
    result: Literal["ok", "needs_changes", "apply_failed"]
    findings: list[GcodeFinding]
    feedback: Feedback
