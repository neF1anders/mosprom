"""Pick the material: the one named in the card, or the best catalog candidate by requirements."""

import itertools
from typing import Any  # noqa: F401  (used in type comments)

from tuning.catalog import find_material, rank_materials
from tuning.catalog.ranking import FAIL, UNKNOWN, WARN, evaluate
from tuning.errors import TuningError

RANK_RULE_ID = "MATERIAL-RANK"


class MaterialChoice(object):
    """The chosen material and everything the user must hear about it."""

    def __init__(self, material, block, unsatisfied, assumptions, infeasible):
        # type: (Any, dict, list, list, bool) -> None
        self.material = material
        self.block = block
        self.unsatisfied = unsatisfied
        self.assumptions = assumptions
        self.infeasible = infeasible


def choose_material(card, materials):
    # type: (dict, dict) -> tuple
    """Return (MaterialChoice, warnings). `materials` is already limited to what the extruder can print."""
    requirements = card.get("requirements", [])
    declared = card.get("material", {})
    warnings = []  # type: list
    if declared.get("name"):
        material = find_material(materials, declared["name"])
        if material is not None:
            return _named(material, requirements, declared), warnings
        warnings.append("material '%s' from the card is not in the catalog, ranking instead" % declared["name"])
    return _ranked(materials, requirements), warnings


def _summary(evaluation):
    parts = []
    for status, label in ((FAIL, "не выполнено"), (WARN, "частично"), (UNKNOWN, "нет данных")):
        items = ["%s (%s)" % (c["requirement_id"], c["detail"]) for c in evaluation["checks"] if c["status"] == status]
        if items:
            parts.append("%s: %s" % (label, "; ".join(items)))
    return "оценка %.2f" % evaluation["score"] + ("; " + "; ".join(parts) if parts else "")


def _check_assumptions(evaluation):
    """Unverified and partly met requirements are told to the user, never shown as confirmed."""
    notes = []
    for check in evaluation["checks"]:
        if check["status"] == UNKNOWN:
            notes.append("требование %s не проверено по каталогу: %s" % (check["requirement_id"], check["detail"]))
        elif check["status"] == WARN and check["hard"]:
            notes.append(
                "обязательное требование %s материал выполняет лишь частично: %s"
                % (check["requirement_id"], check["detail"])
            )
    return notes


def _source_assumptions(requirements):
    return [
        "требование %s = %s — допущение, а не подтверждённый факт" % (r["id"], r["value"])
        for r in requirements
        if r.get("source") == "assumption"
    ]


def _named(material, requirements, declared):
    evaluation = evaluate(material, requirements)
    unsatisfied = [
        {"requirement_id": c["requirement_id"], "why": "материал %s не выполняет: %s" % (material.id, c["detail"])}
        for c in evaluation["checks"]
        if c["status"] == FAIL
    ]
    block = {
        "id": material.id,
        "source": declared.get("source") or "requirement:" + declared.get("requirement_id", "material"),
        "why": "материал указан в задании (%s); %s" % (declared["name"], _summary(evaluation)),
        "alternatives": [],
        "checks": evaluation["checks"],
    }
    assumptions = _source_assumptions(requirements) + _check_assumptions(evaluation)
    return MaterialChoice(material, block, unsatisfied, assumptions, False)


def _ranked(materials, requirements):
    ranked = rank_materials(materials, requirements)
    if not ranked:
        raise TuningError("material catalog has no printable candidates")
    best = ranked[0]
    chosen = materials[best["material"]]
    unsatisfied = _catalog_conflicts(ranked, [r for r in requirements if r.get("hard")])
    block = {
        "id": chosen.id,
        "source": "rule:" + RANK_RULE_ID,
        "why": "лучший из %d материалов каталога по требованиям задания; %s" % (len(ranked), _summary(best)),
        "alternatives": [{"id": e["material"], "why": _summary(e)} for e in ranked[1:3]],
        "checks": best["checks"],
    }
    assumptions = _source_assumptions(requirements) + _check_assumptions(best)
    return MaterialChoice(chosen, block, unsatisfied, assumptions, bool(unsatisfied))


def _failed_ids(evaluation):
    return set(c["requirement_id"] for c in evaluation["checks"] if c["hard"] and c["status"] == FAIL)


def _catalog_conflicts(ranked, hard):
    """Hard requirements no material meets alone, and pairs no single material meets together."""
    failures = [_failed_ids(e) for e in ranked]
    checkable = set(c["requirement_id"] for e in ranked for c in e["checks"] if c["hard"])
    alone = sorted(i for i in checkable if all(i in failed for failed in failures))
    found = [{"requirement_id": i, "why": "ни один материал каталога его не выполняет"} for i in alone]
    rest = sorted(checkable - set(alone))
    for first, second in itertools.combinations(rest, 2):
        if all(first in failed or second in failed for failed in failures):
            found.append(
                {
                    "requirement_id": first,
                    "conflicts_with": second,
                    "why": "ни один материал каталога не выполняет оба обязательных требования",
                }
            )
    return found
