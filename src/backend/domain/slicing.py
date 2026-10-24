"""Contracts of slicing (stage four) and the check of its G-code (stage five).

STE Slicer with the AI Assistant plugin applies a parameter set through the plugin's MCP
tools, slices and saves the G-code and the project. ``SliceReport`` is what that run did;
``GcodeCheck`` is what the G-code shows and what goes back to parameter selection when the
cause lies in the set rather than in how the slicer applied it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import Value
from .parameters import Feedback


class SlicerCall(Value):
    """One MCP tool call of the plan; ``step`` names it in the report."""

    step: str
    tool: str
    args: dict[str, Any]


class Unsupported(Value):
    step: str
    reason: str


class Clamped(Value):
    """A value the slicer wrote differently from the one asked for."""

    key: str
    requested: Any
    written: Any


class CallOutcome(Value):
    step: str
    tool: str
    ok: bool
    error: str | None = None


class SliceReport(Value):
    """``unavailable``: no slicer answered; ``failed``: a call of the plan failed."""

    status: Literal["sliced", "failed", "unavailable"]
    message: str
    steps: list[CallOutcome] = Field(default_factory=list)
    clamped: list[Clamped] = Field(default_factory=list)
    unsupported: list[Unsupported] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Keys of the stored copies and the folder where the slicer saved the originals.
    gcode: str | None = None
    project: str | None = None
    folder: str | None = None
    print_time_seconds: int | None = None
    material_grams: float | None = None
    material_meters: float | None = None


class GcodeFinding(Value):
    """``file``: the G-code is broken; ``apply``: the slicer wrote something else than the
    set asked for; ``content``: the set itself needs a change, for instance a model off the
    bed."""

    id: str
    kind: Literal["file", "apply", "content"]
    level: Literal["error", "warning", "info"]
    message: str
    key: str | None = None


class GcodeCheck(Value):
    result: Literal["ok", "needs_changes", "apply_failed"]
    findings: list[GcodeFinding]
    feedback: Feedback
