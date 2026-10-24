"""Boundary adapter: the stage-1 handoff {idempotency_key, card v1.1} -> task_card/0 + geometry/0 + card_ref."""

import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.intake.card import task_card_from_stage1
from tuning.intake.mesh_report import geometry_from_report
from tuning.serialization import load_json_file

_VOCABULARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocabulary.json")


class Intake(object):
    """What stage 2 takes from one stage-1 handoff."""

    def __init__(self, idempotency_key, card_ref, task_card, geometry, assumptions, warnings):
        # type: (Any, dict, dict, dict, list, list) -> None
        self.idempotency_key = idempotency_key
        self.card_ref = card_ref
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
        warnings.append("bare task card without idempotency_key")
    if not isinstance(card, dict):
        raise TuningError("stage-1 card must be a JSON object")
    task_card, assumptions, card_warnings = task_card_from_stage1(card, load_vocabulary())
    geometry, geometry_assumptions, geometry_warnings = geometry_from_report(card.get("stl_analysis"))
    return Intake(
        key,
        card_ref(card, key),
        task_card,
        geometry,
        assumptions + geometry_assumptions,
        warnings + card_warnings + geometry_warnings,
    )


def card_ref(card, idempotency_key):
    # type: (dict, Any) -> dict
    """{job_id, revision} of the card: the key is "job_uuid:revision"; a bare card names its job in source_versions."""
    revision = card.get("revision")
    job_id = None
    if idempotency_key and ":" in idempotency_key:
        job_id, key_revision = idempotency_key.rsplit(":", 1)
        if revision is None and key_revision.isdigit():
            revision = int(key_revision)
    if job_id is None:
        jobs = [s.get("id") for s in card.get("source_versions") or [] if "revision" in s and s.get("id")]
        job_id = jobs[0] if jobs else None
    if not job_id or isinstance(revision, bool) or not isinstance(revision, int):
        raise TuningError("cannot tell the job and integer revision of the card (idempotency_key, revision)")
    return {"job_id": job_id, "revision": revision}
