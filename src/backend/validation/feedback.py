"""Feedback of the check for stage two's second and last pass.

A finding becomes what stage two can act on: a constraint on a slicer key or on one of its
choices (``quality_type``, ``material``), an orientation candidate to drop, or a warning when
the contract has no operation for it, as for a setting that does not act in the mode. A
finding that means stage two broke its own contract is not feedback: ``stage_two_errors``
returns those so the caller stops with them. Notes for people are not passed on.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from operator import attrgetter
from typing import Literal, TypeVar

from ..domain.parameters import Constraint, Exclusion, Feedback, FeedbackWarning, Issue

Operation = Literal["eq", "ne", "min", "max", "in"]
Severity = Literal["error", "warning"]
Item = TypeVar("Item")

# The constraint each kind asks for; the finding's ``key`` and ``bound`` are its key and value.
_CONSTRAINTS: dict[str, tuple[Operation, Severity]] = {
    "below_min": ("min", "error"),
    "above_max": ("max", "error"),
    "below_recommended": ("min", "warning"),
    "above_recommended": ("max", "warning"),
    "not_in_enum": ("in", "error"),
    "unknown_quality": ("in", "error"),
    "unknown_material": ("in", "error"),
    "wrong_filament": ("ne", "error"),
    "unlinked_mode_key": ("eq", "warning"),
}
# Findings stage two must never produce, and no operation of the contract fixes: a key or a
# JSON type the slicer does not take, an empty or broken set, a model placed off the plate.
_STAGE_TWO_ERRORS = (
    "wrong_printer",
    "no_materials",
    "unknown_key",
    "wrong_type",
    "no_models",
    "bad_scale",
    "bad_position",
    "outside_bed",
    "height_out_of_range",
)
# What becomes of each kind. A kind missing here fails loudly rather than being dropped.
_HANDLING: dict[str, str] = {
    **{kind: "constraint" for kind in _CONSTRAINTS},
    "bad_rotation": "exclusion",
    "inactive_in_mode": "warning",
    "mode_key_mismatch": "warning",
    **{kind: "stage_two_error" for kind in _STAGE_TWO_ERRORS},
    "formula_unknown": "note",
}
# Every kind of finding the check reports.
KINDS = frozenset(_HANDLING)


def build_feedback(issues: list[Issue], iteration: int) -> Feedback:
    """Asks for changes when there is a constraint or an exclusion; warnings alone are ok."""
    constraints = _first(map(_constraint, _handled(issues, "constraint")), attrgetter("id"))
    exclude = _first(map(_exclusion, _handled(issues, "exclusion")), attrgetter("candidate"))
    warnings = [
        FeedbackWarning.model_validate({"key": issue.key, "reason": issue.message})
        for issue in _handled(issues, "warning")
    ]
    return Feedback(
        iteration=iteration,
        result="needs_changes" if constraints or exclude else "ok",
        constraints=constraints,
        exclude=exclude,
        warnings=warnings,
    )


def stage_two_errors(issues: list[Issue]) -> list[Issue]:
    """Findings no feedback can fix: an unknown key, a wrong JSON type, a broken model."""
    return _handled(issues, "stage_two_error")


def _handled(issues: list[Issue], handling: str) -> list[Issue]:
    return [issue for issue in issues if _HANDLING[issue.kind] == handling]


def _constraint(issue: Issue) -> Constraint:
    op, severity = _CONSTRAINTS[issue.kind]
    return Constraint.model_validate(
        {
            "id": f"{issue.kind}.{issue.key}",
            "key": issue.key,
            "op": op,
            "value": issue.bound,
            "reason": issue.message,
            "severity": severity,
        }
    )


def _exclusion(issue: Issue) -> Exclusion:
    return Exclusion(type="orientation", candidate=issue.bound, reason=issue.message)


def _first(items: Iterable[Item], identity: Callable[[Item], Hashable]) -> list[Item]:
    """The first item of each identity, in order: stage two picks one material for all
    extruders, so two extruders with the same finding ask for one constraint."""
    first: dict[Hashable, Item] = {}
    for item in items:
        first.setdefault(identity(item), item)
    return list(first.values())
