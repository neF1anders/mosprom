"""Order of the steps after a ready card: selection, its check, slicing and the G-code check.

Selection runs at most twice, so the check of the set and the check of the G-code share the
one return to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .parameters import MAX_ITERATIONS

StepName = Literal["parameters", "validation", "slicing", "gcode"]
# What a finished step decided: a check passes or asks for changes; a selection may find
# that nothing satisfies the card, for instance a model larger than every working area;
# slicing fails when the slicer is not there or refuses a call.
Verdict = Literal["ok", "needs_changes", "infeasible", "failed"]


@dataclass(frozen=True)
class Step:
    stage: StepName
    iteration: int


FIRST_STEP = Step("parameters", 1)


def next_step(step: Step, verdict: Verdict | None = None) -> Step | None:
    """The step after ``step`` given its verdict.

    A selection is checked unless it is infeasible: such a set cannot be printed as it is, and
    what the check would find is only its consequence. A check that asks for changes sends
    the work back to selection while a pass is left; the last pass is sliced with what is
    left, and the chat shows it. The G-code check may send it back the same way.
    """
    if step.stage == "parameters":
        return None if verdict == "infeasible" else Step("validation", step.iteration)
    if step.stage == "slicing":
        return None if verdict == "failed" else Step("gcode", step.iteration)
    if verdict == "needs_changes" and step.iteration < MAX_ITERATIONS:
        return Step("parameters", step.iteration + 1)
    return Step("slicing", step.iteration) if step.stage == "validation" else None
