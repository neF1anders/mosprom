"""select_parameters: stage-1 handoff (+ stage-3 feedback on the second iteration) -> stage2.parameter_set v0.1."""

import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.decisions import Decisions
from tuning.errors import TuningError
from tuning.feedback import read_feedback
from tuning.intake import read_handoff
from tuning.output import render


def select_parameters(payload, feedback=None, config=None):
    # type: (dict, Any, Any) -> dict
    """First iteration: feedback=None. Second and last: the stage-3 feedback on the first proposal.

    Nothing is kept between calls: the same card and feedback always give the same parameter set.
    """
    intake = read_handoff(payload)
    parsed = read_feedback(feedback) if feedback is not None else None
    decisions = Decisions(intake.task_card, intake.geometry, _materials_dir(config or {}), parsed)
    return render(intake, decisions, 2 if parsed is not None else 1)


def _materials_dir(config):
    directory = config.get("materials_dir") or os.environ.get("STE_MATERIALS_DIR")
    if not directory:
        raise TuningError("materials directory is not set: pass --materials-dir or set STE_MATERIALS_DIR")
    if not os.path.isdir(directory):
        raise TuningError("materials directory does not exist: %s" % directory)
    return directory
