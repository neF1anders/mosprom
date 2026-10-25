from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from operator import attrgetter
from typing import Literal, TypeVar

from ..domain.parameters import Constraint, Exclusion, Feedback, FeedbackWarning, Issue

Operation = Literal["eq", "ne", "min", "max", "in"]
Severity = Literal["error", "warning"]
Item = TypeVar("Item")

# ограничение по виду
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
# запрещённые находки этапа
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
# судьба каждого вида
_HANDLING: dict[str, str] = {
    **{kind: "constraint" for kind in _CONSTRAINTS},
    "bad_rotation": "exclusion",
    "inactive_in_mode": "warning",
    "mode_key_mismatch": "warning",
    **{kind: "stage_two_error" for kind in _STAGE_TWO_ERRORS},
    "formula_unknown": "note",
}
# все виды замечаний
KINDS = frozenset(_HANDLING)


def build_feedback(issues: list[Issue], iteration: int) -> Feedback:
    """Просит правок при ограничениях."""
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
    """Замечания, которые не исправить."""
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
    """Первый элемент каждой идентичности."""
    first: dict[Hashable, Item] = {}
    for item in items:
        first.setdefault(identity(item), item)
    return list(first.values())
