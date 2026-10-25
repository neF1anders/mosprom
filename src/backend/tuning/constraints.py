from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ..domain.parameters import Constraint
from .axes import Axis, SearchSpace
from .notes import ConstraintResult, Unmet
from .planning import Chosen, Plan, find_conflicts, limit_axis

# ключи верхнего уровня
MODE_KEY, QUALITY_KEY, MATERIAL_KEY = "printing_mode", "quality_type", "material"
_CHOICE_KEYS = (MODE_KEY, QUALITY_KEY, MATERIAL_KEY)


@dataclass(frozen=True)
class Forced:
    value: Any
    constraint_id: str


@dataclass(frozen=True)
class Choices:
    """Навязанные и запрещённые значения выбора."""

    forced: Mapping[str, Forced] = field(default_factory=dict)
    allowed: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    banned: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)

    def permits(self, name: str, value: Any) -> bool:
        if value in self.banned.get(name, ()):
            return False
        return name not in self.allowed or value in self.allowed[name]


@dataclass(frozen=True)
class PassThrough:
    """Значение ключа вне модели."""

    value: Any
    reason: str
    constraint_id: str


@dataclass(frozen=True)
class ConstraintOutcome:
    plan: Plan
    pass_through: Mapping[str, PassThrough]
    results: tuple[ConstraintResult, ...]
    unmet: tuple[Unmet, ...]


@dataclass(frozen=True)
class _AxisTarget:
    axis_id: str
    domain: Literal["value", "thickness", "lines"]


@dataclass(frozen=True)
class _DiscreteTarget:
    discrete_id: str


def is_choice(constraint: Constraint) -> bool:
    return constraint.key in _CHOICE_KEYS


def choices_from(constraints: Sequence[Constraint]) -> Choices:
    """Поздние ограничения перекрывают ранние."""
    choices = Choices()
    for constraint in constraints:
        if is_choice(constraint):
            choices = _restrict(choices, constraint)
    return choices


def _restrict(choices: Choices, constraint: Constraint) -> Choices:
    name, value = constraint.key, constraint.value
    if constraint.op == "eq":
        forced = Forced(value, constraint.id)
        return replace(choices, forced={**choices.forced, name: forced})
    if constraint.op == "ne":
        banned = (*choices.banned.get(name, ()), value)
        return replace(choices, banned={**choices.banned, name: banned})
    if constraint.op == "in":
        return replace(choices, allowed={**choices.allowed, name: tuple(value)})
    return choices


def apply_constraints(
    plan: Plan,
    constraints: Sequence[Constraint],
    axes: Mapping[str, Axis],
    space: SearchSpace,
    line_width: float,
) -> ConstraintOutcome:
    """Применяет ограничения проверки к настройкам."""
    index = _index(axes, space)
    pass_through: dict[str, PassThrough] = {}
    notes: list[tuple[Constraint, str | None]] = []
    limited: dict[str, str] = {}
    for constraint in constraints:
        target = index.get(constraint.key)
        if isinstance(target, _AxisTarget):
            plan, note = _limit_axis(plan, constraint, axes[target.axis_id], target, line_width)
            limited[constraint.id] = target.axis_id
        elif isinstance(target, _DiscreteTarget):
            plan, note = _restrict_discrete(plan, constraint, target.discrete_id)
        else:
            note = _pass_through(constraint, pass_through)
        notes.append((constraint, note))
    conflicting = {conflict.axis_id for conflict in find_conflicts(plan)}
    results, unmet = [], []
    for constraint, note in notes:
        if note is not None:
            results.append(ConstraintResult(constraint.id, "not_applied", note))
            unmet.append(Unmet(f"constraint:{constraint.id}", note))
        elif limited.get(constraint.id) in conflicting:
            why = (
                f"{constraint.key} {constraint.op} {constraint.value!r} conflicts with other limits"
            )
            results.append(ConstraintResult(constraint.id, "not_applied", why))
        else:
            why = constraint.reason or constraint.key
            results.append(ConstraintResult(constraint.id, "applied", why))
    return ConstraintOutcome(plan, pass_through, tuple(results), tuple(unmet))


def _index(
    axes: Mapping[str, Axis], space: SearchSpace
) -> dict[str, _AxisTarget | _DiscreteTarget]:
    """Индекс ключей слайсера по ограничениям."""
    index: dict[str, _AxisTarget | _DiscreteTarget] = {
        axis.key: _AxisTarget(axis.id, "thickness" if axis.spec.emit_as else "value")
        for axis in axes.values()
    }
    index["wall_line_count"] = _AxisTarget("wall_line_count", "lines")
    for item in space.discrete:
        for key in item.constrained_keys():
            index[key] = _DiscreteTarget(item.id)
    return index


def _limit_axis(
    plan: Plan, constraint: Constraint, axis: Axis, target: _AxisTarget, line_width: float
) -> tuple[Plan, str | None]:
    op, value = constraint.op, constraint.value
    if (
        op not in ("eq", "min", "max")
        or isinstance(value, bool)
        or not isinstance(value, int | float)
    ):
        return plan, f"op {op} with value {value!r} is not supported on {constraint.key}"
    # линии этой ширины
    limit = value / line_width if target.domain == "thickness" else value
    minimum = limit if op in ("eq", "min") else None
    maximum = limit if op in ("eq", "max") else None
    return limit_axis(plan, axis, f"constraint:{constraint.id}", minimum, maximum), None


def _restrict_discrete(
    plan: Plan, constraint: Constraint, discrete_id: str
) -> tuple[Plan, str | None]:
    rule_id = f"constraint:{constraint.id}"
    restricted = {**plan.restricted_by, discrete_id: rule_id}
    if constraint.op == "eq":
        chosen = Chosen(constraint.value, rule_id)
        return replace(plan, discrete={**plan.discrete, discrete_id: chosen}), None
    if constraint.op == "ne":
        banned = (*plan.banned.get(discrete_id, ()), constraint.value)
        return replace(
            plan, banned={**plan.banned, discrete_id: banned}, restricted_by=restricted
        ), None
    if constraint.op == "in":
        allowed = {**plan.allowed, discrete_id: tuple(constraint.value)}
        return replace(plan, allowed=allowed, restricted_by=restricted), None
    return plan, f"op {constraint.op} is not supported on {constraint.key}"


def _pass_through(constraint: Constraint, pass_through: dict[str, PassThrough]) -> str | None:
    """Требуемое значение ключа без изменений."""
    op, value = constraint.op, constraint.value
    if op == "ne":
        return (
            f"stage 2 does not model {constraint.key} and cannot pick a value other than {value!r}"
        )
    if op == "in" and not value:
        return f"op in with no values is not supported on {constraint.key}"
    chosen = value[0] if op == "in" else value
    pass_through[constraint.key] = PassThrough(chosen, constraint.reason, constraint.id)
    return None


def wall_lines(thickness: float, line_width: float) -> int:
    """Число линий стенки по толщине."""
    if thickness == 0:
        return 0
    return max(1, int(round((thickness - line_width) / line_width)) + 1)
