"""Order of the steps after a ready card: parameter selection, then its check, at most twice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .parameters import MAX_ITERATIONS

StepName = Literal["parameters", "validation"]


@dataclass(frozen=True)
class Step:
    stage: StepName
    iteration: int


FIRST_STEP = Step("parameters", 1)


def next_step(step: Step, check: Literal["ok", "needs_changes"] | None = None) -> Step | None:
    """The step after ``step``; ``check`` is the verdict of a finished check.

    A selection is always checked. A check that asks for changes sends the work back to
    selection once; after the last pass the pipeline stops whatever the verdict.
    """
    if step.stage == "parameters":
        return Step("validation", step.iteration)
    if check == "needs_changes" and step.iteration < MAX_ITERATIONS:
        return Step("parameters", step.iteration + 1)
    return None
