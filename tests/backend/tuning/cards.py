"""Synthetic stage-one task cards (TaskCard 2.0) with an embedded STL analysis report."""

from __future__ import annotations

from typing import Any

from src.backend.domain.models import Requirement, TaskCard
from src.backend.domain.parameters import Feedback

SHA = "0" * 64


def report(size=(20.0, 20.0, 20.0), coordinate_unit="unknown", volume=8000.0) -> dict[str, Any]:
    """Only the report fields stage two reads, in the layout of ``src/mesh_analysis.py``."""
    return {
        "schema_version": "1.0",
        "file": {"sha256": SHA, "triangles": 12, "encoding": "binary"},
        "units": {
            "input_unit": coordinate_unit,
            "coordinate_unit": coordinate_unit,
            "scale_applied": 1,
        },
        "geometry": {
            "bounds": [[0.0, 0.0, 0.0], list(size)],
            "extents": list(size),
            "volume": volume,
            "surface_area": 2400.0,
        },
        "topology": {
            "watertight": True,
            "winding_consistent": True,
            "components": [{"signed_volume": volume}],
        },
        "validation": {"defects": []},
        "normal_chords": {"status": "estimated", "minimum_sampled": 20.0},
        "partial_errors": {},
        "warnings": [
            "Self-intersections and intersections/nesting between shells are not checked."
        ],
    }


def requirement(
    key, value, unit=None, mandatory=True, provenance="user", verified=True
) -> dict[str, Any]:
    return Requirement(
        key=key,
        label=key,
        value=value,
        unit=unit,
        mandatory=mandatory,
        provenance=provenance,
        sources=[{"source_id": "s1", "quote": "synthetic"}],
        verified=verified,
    ).model_dump()


def card(stl_report=None, answers=None, assumptions=(), **fields) -> TaskCard:
    payload = {
        "job_id": "job-1",
        "revision": 1,
        "purpose": "test bracket",
        "readiness": "ready",
        "allowed_actions": ["select_parameters"],
        "assumptions": [{"text": text} for text in assumptions],
        "questions": [
            {"id": question, "kind": "clarify", "title": question, "answer": answer}
            for question, answer in (answers or {}).items()
        ],
        "stl_analysis": {"attachment_id": "att-1", "sha256": SHA, "report": stl_report or report()},
    }
    payload.update(fields)
    return TaskCard.model_validate(payload)


def constraint(constraint_id, key, op, value, reason="synthetic") -> dict[str, Any]:
    return {"id": constraint_id, "key": key, "op": op, "value": value, "reason": reason}


def feedback_payload(*constraints, **fields) -> dict[str, Any]:
    payload = {
        "contract": "stage3.feedback",
        "version": "0.1",
        "iteration": 1,
        "result": "needs_changes",
        "constraints": list(constraints),
        "exclude": [],
        "warnings": [],
    }
    payload.update(fields)
    return payload


def feedback(*constraints, **fields) -> Feedback:
    return Feedback.model_validate(feedback_payload(*constraints, **fields))
