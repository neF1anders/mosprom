"""Stage-3 feedback (`stage3.feedback` v0.1) -> constraints for the second and last iteration."""

import re
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError

CONTRACT = "stage3.feedback"
VERSION = "0.1"
OPERATIONS = ("eq", "ne", "min", "max", "in")
LAST_ITERATION = 2
# Constraint ids end up in `source: constraint:<id>`, which the stage-3 checker matches against this pattern.
_ID_PATTERN = re.compile(r"^[\w\-.]+$")


class Feedback(object):
    """What the validator demands before the next proposal."""

    def __init__(self, iteration, constraints, excluded_orientations, other_exclusions, warnings):
        # type: (int, list, list, list, list) -> None
        self.iteration = iteration
        self.constraints = constraints
        self.excluded_orientations = excluded_orientations
        self.other_exclusions = other_exclusions
        self.warnings = warnings


def read_feedback(payload):
    # type: (Any) -> Feedback
    if not isinstance(payload, dict) or payload.get("contract") != CONTRACT:
        raise TuningError("feedback must be a %s object" % CONTRACT)
    if payload.get("version") != VERSION:
        raise TuningError("unsupported feedback version %r, expected %s" % (payload.get("version"), VERSION))
    iteration = payload.get("iteration")
    if iteration != LAST_ITERATION - 1:
        raise TuningError(
            "feedback is for iteration %r; only iteration 1 can be revised (at most %d)" % (iteration, LAST_ITERATION)
        )
    constraints = [_constraint(item, index) for index, item in enumerate(payload.get("constraints") or [])]
    seen = set()
    for constraint in constraints:
        if constraint["id"] in seen:
            raise TuningError("feedback has two constraints with id %r" % constraint["id"])
        seen.add(constraint["id"])
    orientations, others = [], []  # type: list, list
    for exclusion in payload.get("exclude") or []:
        (orientations if exclusion.get("type") == "orientation" else others).append(exclusion)
    return Feedback(iteration, constraints, orientations, others, list(payload.get("warnings") or []))


def _constraint(item, index):
    for field in ("id", "key", "op"):
        if not item.get(field):
            raise TuningError("feedback constraint #%d has no %s" % (index, field))
    if not _ID_PATTERN.match("%s" % item["id"]):
        raise TuningError("feedback constraint id %r must be letters, digits, '-', '_' or '.'" % item["id"])
    if item["op"] not in OPERATIONS:
        raise TuningError("feedback constraint %s has unknown op %r" % (item["id"], item["op"]))
    if "value" not in item:
        raise TuningError("feedback constraint %s has no value" % item["id"])
    if item["op"] == "in" and not isinstance(item["value"], list):
        raise TuningError("feedback constraint %s: op 'in' needs a list" % item["id"])
    return {
        "id": "%s" % item["id"],
        "key": item["key"],
        "op": item["op"],
        "value": item["value"],
        "reason": item.get("reason") or "",
        "severity": item.get("severity") or "error",
    }
