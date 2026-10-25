from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import Job
from .parameters import MAX_ITERATIONS

StepName = Literal["parameters", "validation", "slicing", "gcode"]
# итог шага
Verdict = Literal["ok", "needs_changes", "infeasible", "failed"]


@dataclass(frozen=True)
class Step:
    stage: StepName
    iteration: int


FIRST_STEP = Step("parameters", 1)


def next_step(step: Step, verdict: Verdict | None = None) -> Step | None:
    """Следующий шаг по вердикту."""
    if step.stage == "parameters":
        return None if verdict == "infeasible" else Step("validation", step.iteration)
    if step.stage == "slicing":
        return None if verdict == "failed" else Step("gcode", step.iteration)
    if verdict == "needs_changes" and step.iteration < MAX_ITERATIONS:
        return Step("parameters", step.iteration + 1)
    return Step("slicing", step.iteration) if step.stage == "validation" else None


def restart(job: Job) -> None:
    """Новая работа в ревизии."""
    job.stage, job.work_revision = "understanding", job.revision
    job.parameters = job.result = job.outcome = None
