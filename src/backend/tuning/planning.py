"""Turn fired rules into a plan: per axis a shift and an allowed interval of t, discrete choices
and the requirements the rules find unmet.

The start point is not part of the plan: it is the value the slicer would use anyway (quality
profile, material, definition) and is known only once the quality profile is chosen, see
``resolve_t``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .axes import Axis, AxisContext, t_interval_for_limits
from .notes import EPSILON, Unmet
from .rules import (
    Action,
    BoundAction,
    LimitAction,
    MinLayersAction,
    Rule,
    SetDiscreteAction,
    ShiftAction,
    StartAction,
    UnsatisfiedAction,
    requirement_keys,
)


@dataclass(frozen=True)
class AxisPlan:
    shift: float = 0.0
    low: float = 0.0
    high: float = 1.0
    # Rules that shift the axis, in the order they fired.
    moving_rule_ids: tuple[str, ...] = ()
    low_rule: str | None = None
    high_rule: str | None = None
    # A start value in t that replaces the slicer's own, and the rule that set it.
    start: float | None = None
    start_rule: str | None = None


@dataclass(frozen=True)
class Chosen:
    value: Any
    rule_id: str


@dataclass(frozen=True)
class LayerMinimum:
    layers: int
    rule_id: str


@dataclass(frozen=True)
class Finding:
    requirement_key: str
    why: str
    rule_id: str


@dataclass(frozen=True)
class Conflict:
    axis_id: str
    rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    axes: Mapping[str, AxisPlan]
    discrete: Mapping[str, Chosen] = field(default_factory=dict)
    banned: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    allowed: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    restricted_by: Mapping[str, str] = field(default_factory=dict)
    min_layers: Mapping[str, LayerMinimum] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()

    def with_axis(self, axis_id: str, entry: AxisPlan) -> Plan:
        return replace(self, axes={**self.axes, axis_id: entry})


def build_plan(fired: Sequence[Rule], axes: Mapping[str, Axis], context: AxisContext) -> Plan:
    """Fired rules in file order; for a discrete setting the later rule wins."""
    plan = Plan(axes={axis_id: AxisPlan() for axis_id in axes})
    for rule in fired:
        for action in rule.then:
            plan = _apply(plan, action, rule.id, axes, context)
    return plan


def limit_axis(
    plan: Plan, axis: Axis, rule_id: str, minimum: float | None, maximum: float | None
) -> Plan:
    """Hard limits in the value domain (None = open), from a rule or a check constraint."""
    low, high = t_interval_for_limits(axis, minimum, maximum)
    entry = _lower_high(_raise_low(plan.axes[axis.id], rule_id, low), rule_id, high)
    return plan.with_axis(axis.id, entry)


def find_conflicts(plan: Plan) -> list[Conflict]:
    """Axes whose hard interval is empty, with the rules that bound it."""
    conflicts = []
    for axis_id, entry in sorted(plan.axes.items()):
        if entry.low > entry.high + EPSILON:
            rules = {rule for rule in (entry.low_rule, entry.high_rule) if rule is not None}
            conflicts.append(Conflict(axis_id, tuple(sorted(rules))))
    return conflicts


def plan_unmet(
    plan: Plan,
    conflicts: Sequence[Conflict],
    requirement_ids: Mapping[str, Sequence[str]],
    rules: Mapping[str, Rule],
) -> list[Unmet]:
    """Findings and conflicts named by the card requirements behind them, else by the rule."""

    def reference(rule_id: str) -> str:
        rule = rules.get(rule_id)
        if rule is None:
            return rule_id
        found = [id_ for key in requirement_keys(rule) for id_ in requirement_ids.get(key, [])]
        return found[0] if found else f"rule:{rule_id}"

    unmet = [
        Unmet(requirement_id, finding.why)
        for finding in plan.findings
        for requirement_id in requirement_ids.get(
            finding.requirement_key, [f"rule:{finding.rule_id}"]
        )
    ]
    for conflict in conflicts:
        unmet.append(_conflict_unmet(conflict, reference))
    return unmet


def _conflict_unmet(conflict: Conflict, reference: Callable[[str], str]) -> Unmet:
    if len(conflict.rule_ids) == 1:
        (rule_id,) = conflict.rule_ids
        why = f"ограничение {rule_id} требует значения {conflict.axis_id} вне пределов подбора"
        return Unmet(reference(rule_id), why)
    first, second = conflict.rule_ids
    why = f"ограничения {first} и {second} требуют несовместимых значений {conflict.axis_id}"
    return Unmet(reference(first), why, conflicts_with=reference(second))


def resolve_t(entry: AxisPlan, baseline_t: float) -> tuple[float, str | None]:
    """t and the rule that decided it (None: the slicer value stands).

    The start (a rule's start value, else the slicer value) is brought inside the hard
    interval, shifted by the rules, then kept inside the interval again; a limit that cut the
    shift decides the value. An empty interval collapses to its middle.
    """
    low, high = entry.low, entry.high
    if low > high:
        low = high = (low + high) / 2.0
    preferred = baseline_t if entry.start is None else entry.start
    start = min(max(preferred, low), high)
    raw = start + entry.shift
    t = min(max(raw, low), high)
    if raw > high + EPSILON and entry.high_rule:
        return t, entry.high_rule
    if raw < low - EPSILON and entry.low_rule:
        return t, entry.low_rule
    if entry.moving_rule_ids and abs(entry.shift) > EPSILON:
        return t, entry.moving_rule_ids[-1]
    if abs(start - preferred) > EPSILON:
        return t, entry.low_rule if preferred < low else entry.high_rule
    if abs(start - baseline_t) > EPSILON:
        return t, entry.start_rule
    return t, None


def _shift(entry: AxisPlan, rule_id: str, delta: float) -> AxisPlan:
    moving = entry.moving_rule_ids
    if rule_id not in moving:
        moving = (*moving, rule_id)
    return replace(entry, shift=entry.shift + delta, moving_rule_ids=moving)


def _raise_low(entry: AxisPlan, rule_id: str, bound: float) -> AxisPlan:
    return replace(entry, low=bound, low_rule=rule_id) if bound > entry.low else entry


def _lower_high(entry: AxisPlan, rule_id: str, bound: float) -> AxisPlan:
    return replace(entry, high=bound, high_rule=rule_id) if bound < entry.high else entry


def _apply(
    plan: Plan, action: Action, rule_id: str, axes: Mapping[str, Axis], context: AxisContext
) -> Plan:
    """Mode votes are counted by the mode choice, not by the plan."""
    match action:
        case ShiftAction():
            entry = _shift(plan.axes[action.param], rule_id, action.delta)
            return plan.with_axis(action.param, entry)
        case BoundAction():
            return plan.with_axis(action.param, _bound(plan.axes[action.param], action, rule_id))
        case LimitAction():
            minimum = None if action.minimum is None else context.number(action.minimum)
            maximum = None if action.maximum is None else context.number(action.maximum)
            return limit_axis(plan, axes[action.param], rule_id, minimum, maximum)
        case StartAction():
            start = axes[action.param].clamped_t_of(context.number(action.value))
            entry = replace(plan.axes[action.param], start=start, start_rule=rule_id)
            return plan.with_axis(action.param, entry)
        case MinLayersAction():
            layers = LayerMinimum(action.minimum, rule_id)
            return replace(plan, min_layers={**plan.min_layers, action.param: layers})
        case SetDiscreteAction():
            chosen = Chosen(action.value, rule_id)
            return replace(plan, discrete={**plan.discrete, action.param: chosen})
        case UnsatisfiedAction():
            finding = Finding(action.requirement_key, action.why, rule_id)
            return replace(plan, findings=(*plan.findings, finding))
    return plan


def _bound(entry: AxisPlan, action: BoundAction, rule_id: str) -> AxisPlan:
    if action.min_t is not None:
        entry = _raise_low(entry, rule_id, action.min_t)
    if action.max_t is not None:
        entry = _lower_high(entry, rule_id, action.max_t)
    return entry
