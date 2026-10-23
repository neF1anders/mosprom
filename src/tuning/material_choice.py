"""Pick the material: the one named in the card, or the best catalog candidate by requirements."""

import itertools
from typing import Any  # noqa: F401  (used in type comments)

from tuning.catalog import find_material, rank_materials
from tuning.catalog.ranking import FAIL, UNKNOWN, WARN, evaluate
from tuning.errors import TuningError


class MaterialChoice(object):
    def __init__(self, material, block, unsatisfied, assumptions, infeasible):
        # type: (Any, dict, list, list, bool) -> None
        self.material = material
        self.block = block
        self.unsatisfied = unsatisfied
        self.assumptions = assumptions
        self.infeasible = infeasible


def choose_material(card, materials):
    # type: (dict, dict) -> tuple
    """Return (MaterialChoice, warnings)."""
    requirements = card.get("requirements", [])
    declared = card.get("material", {})
    warnings = []  # type: list
    candidates = materials
    if declared.get("candidates"):
        names = set(name.strip().lower() for name in declared["candidates"])
        candidates = {m.id: m for m in materials.values() if m.id.lower() in names or m.label.lower() in names}
    if declared.get("name"):
        material = find_material(materials, declared["name"])
        if material is not None:
            return _named(material, requirements, declared), warnings
        warnings.append("material '%s' from the card is not in the catalog, ranking instead" % declared["name"])
    return _ranked(candidates, requirements), warnings


def _summary(evaluation):
    parts = []
    for status in (FAIL, WARN, UNKNOWN):
        items = ["%s (%s)" % (c["requirement_id"], c["detail"]) for c in evaluation["checks"] if c["status"] == status]
        if items:
            parts.append("%s: %s" % (status, "; ".join(items)))
    return "score %.2f" % evaluation["score"] + ("; " + "; ".join(parts) if parts else "")


def _unchecked_assumptions(evaluation):
    return [
        "%s %s: not verified from the catalog (%s)" % (c["requirement_id"], c["key"], c["detail"])
        for c in evaluation["checks"]
        if c["status"] == UNKNOWN
    ]


def _source_assumptions(requirements):
    return [
        "%s %s=%s is an assumption%s" % (r["id"], r["key"], r["value"], (": " + r["basis"]) if r.get("basis") else "")
        for r in requirements
        if r.get("source") == "assumption"
    ]


def _named(material, requirements, declared):
    evaluation = evaluate(material, requirements)
    unsatisfied = [
        {"requirement_id": c["requirement_id"], "why": "material '%s' fails: %s" % (material.id, c["detail"])}
        for c in evaluation["checks"]
        if c["status"] == FAIL
    ]
    block = {
        "value": material.id,
        "source": "card",
        "reason": "material named in the task card (%s); %s"
        % (declared.get("source") or "unspecified origin", _summary(evaluation)),
        "alternatives": [],
        "checks": evaluation["checks"],
    }
    return MaterialChoice(
        material, block, unsatisfied, _source_assumptions(requirements) + _unchecked_assumptions(evaluation), False
    )


def _ranked(materials, requirements):
    ranked = rank_materials(materials, requirements)
    if not ranked:
        raise TuningError("material catalog has no printable candidates")
    best = ranked[0]
    chosen = materials[best["material"]]
    hard = [r for r in requirements if r.get("hard")]
    unsatisfied = _catalog_conflicts(ranked, hard)
    block = {
        "value": chosen.id,
        "source": "rank",
        "reason": "best of %d catalog materials; %s" % (len(ranked), _summary(best)),
        "alternatives": [{"value": e["material"], "reason": _summary(e)} for e in ranked[1:3]],
        "checks": best["checks"],
    }
    return MaterialChoice(
        chosen, block, unsatisfied, _source_assumptions(requirements) + _unchecked_assumptions(best), bool(unsatisfied)
    )


def _failed_ids(evaluation):
    return set(c["requirement_id"] for c in evaluation["checks"] if c["hard"] and c["status"] == FAIL)


def _catalog_conflicts(ranked, hard):
    """Hard requirements no material meets alone, and pairs no single material meets together."""
    failures = [_failed_ids(e) for e in ranked]
    checkable = set(c["requirement_id"] for e in ranked for c in e["checks"] if c["hard"])
    alone = sorted(i for i in checkable if all(i in failed for failed in failures))
    found = [{"requirement_id": i, "why": "no catalog material satisfies it"} for i in alone]
    rest = sorted(checkable - set(alone))
    for first, second in itertools.combinations(rest, 2):
        if all(first in failed or second in failed for failed in failures):
            found.append(
                {
                    "requirement_id": first,
                    "conflicts_with": second,
                    "why": "no catalog material satisfies both hard requirements",
                }
            )
    return found
