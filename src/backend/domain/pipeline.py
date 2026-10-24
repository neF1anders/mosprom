"""Order of the steps after a ready card: parameter selection, then its check, at most twice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .parameters import MAX_ITERATIONS

StepName = Literal["parameters", "validation"]
# What a finished step decided: a check passes or asks for changes; a selection may find
# that nothing satisfies the card, for instance a model larger than every working area.
Verdict = Literal["ok", "needs_changes", "infeasible"]


@dataclass(frozen=True)
class Step:
    stage: StepName
    iteration: int


FIRST_STEP = Step("parameters", 1)


def next_step(step: Step, verdict: Verdict | None = None) -> Step | None:
    """The step after ``step`` given its verdict.

    A selection is checked unless it is infeasible: such a set cannot be printed as it is, and
    what the check would find is only its consequence. A check that asks for changes sends
    the work back to selection once; after the last pass the pipeline stops either way.
    """
    if step.stage == "parameters":
        return None if verdict == "infeasible" else Step("validation", step.iteration)
    if verdict == "needs_changes" and step.iteration < MAX_ITERATIONS:
        return Step("parameters", step.iteration + 1)
    return None
