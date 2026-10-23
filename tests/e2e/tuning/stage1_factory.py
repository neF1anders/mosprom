"""Synthetic stage-1 handoffs: {idempotency_key, card v1.1} with an embedded STL analysis report."""

import copy
import json

SHA = "0" * 64


def report(size=(20.0, 20.0, 20.0), coordinate_unit="unknown", volume=8000.0):
    """Only the report fields stage 2 reads, in the analyser's layout."""
    return {
        "schema_version": "1.0",
        "file": {"sha256": SHA, "triangles": 12, "encoding": "binary"},
        "units": {"input_unit": coordinate_unit, "coordinate_unit": coordinate_unit, "scale_applied": 1},
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
        "warnings": ["Self-intersections and intersections/nesting between shells are not checked."],
    }


def requirement(key, value, unit=None, mandatory=True, provenance="user", verified=True):
    return {
        "label": key,
        "key": key,
        "value": value,
        "unit": unit,
        "conditions": "",
        "mandatory": mandatory,
        "provenance": provenance,
        "sources": [{"source_id": "s1", "quote": "synthetic", "page": None}],
        "verified": verified,
    }


BASE_CARD = {
    "schema_version": "1.1",
    "revision": 1,
    "purpose": "test bracket",
    "requirements": [],
    "preferences": [],
    "production_constraints": [],
    "assumptions": [],
    "unknowns": [],
    "questions": [],
    "conflicts": [],
    "allowed_actions": ["select_parameters"],
    "blocked_actions": {},
    "readiness": "ready",
    "answers": {},
    "resolutions": {},
}


def handoff(key="job-1:1", stl_report=None, **fields):
    card = copy.deepcopy(BASE_CARD)
    card.update(fields)
    card["stl_analysis"] = {"attachment_id": "att-1", "sha256": SHA, "report": stl_report or report()}
    return {"idempotency_key": key, "card": card}


def write_handoff(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def constraint(constraint_id, key, op, value, reason="synthetic"):
    return {"id": constraint_id, "key": key, "op": op, "value": value, "reason": reason, "severity": "error"}


def feedback(*constraints, **fields):
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
