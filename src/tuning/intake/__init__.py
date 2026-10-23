"""Boundary adapter: the stage-1 handoff {idempotency_key, card v1.1} -> task_card/0 + geometry/0."""

import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.intake.card import task_card_from_stage1
from tuning.intake.mesh_report import geometry_from_report
from tuning.select import select_parameters
from tuning.serialization import load_json_file

_VOCABULARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocabulary.json")


class Intake(object):
    """What stage 2 takes from one stage-1 handoff."""

    def __init__(self, idempotency_key, task_card, geometry, assumptions, warnings):
        # type: (Any, dict, dict, list, list) -> None
        self.idempotency_key = idempotency_key
        self.task_card = task_card
        self.geometry = geometry
        self.assumptions = assumptions
        self.warnings = warnings


def load_vocabulary():
    # type: () -> dict
    return load_json_file(_VOCABULARY_PATH)


def read_handoff(payload):
    # type: (dict) -> Intake
    """Accept the POST body {idempotency_key, card} or a bare card exported from the stage-1 API."""
    if not isinstance(payload, dict):
        raise TuningError("stage-1 handoff must be a JSON object")
    warnings = []
    if "card" in payload:
        card, key = payload["card"], payload.get("idempotency_key")
    else:
        card, key = payload, None
        warnings.append("bare task card without idempotency_key: loop calls are not tied to a revision")
    if not isinstance(card, dict):
        raise TuningError("stage-1 card must be a JSON object")
    task_card, assumptions, card_warnings = task_card_from_stage1(card, load_vocabulary())
    geometry, geometry_assumptions, geometry_warnings = geometry_from_report(card.get("stl_analysis"))
    return Intake(
        key, task_card, geometry, assumptions + geometry_assumptions, warnings + card_warnings + geometry_warnings
    )


def select_from_handoff(payload, state=None, verdict=None, config=None):
    # type: (dict, Any, Any, Any) -> tuple
    """select_parameters for a stage-1 handoff; the idempotency key ties loop calls to one card revision."""
    intake = read_handoff(payload)
    if state is not None and state.get("idempotency_key") != intake.idempotency_key:
        raise TuningError(
            "state belongs to handoff %r, not %r" % (state.get("idempotency_key"), intake.idempotency_key)
        )
    param_set, new_state = select_parameters(intake.task_card, intake.geometry, state, verdict, config)
    param_set["idempotency_key"] = intake.idempotency_key
    param_set["assumptions_used"] = intake.assumptions + param_set["assumptions_used"]
    param_set["warnings"] = intake.warnings + param_set["warnings"]
    new_state["idempotency_key"] = intake.idempotency_key
    return param_set, new_state
