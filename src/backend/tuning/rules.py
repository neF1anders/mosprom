from __future__ import annotations

import operator
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..domain.models import Value
from .axes import NumberSpec

FactValue = bool | int | float | str | tuple[str, ...]
Facts = Mapping[str, FactValue]


class Always(Value):
    """Пустое условие, всегда верное."""


class AllOf(Value):
    all: list[Condition]


class AnyOf(Value):
    any: list[Condition]


class Negation(Value):
    negated: Condition = Field(alias="not")


class Comparison(Value):
    fact: str
    op: Literal[">", ">=", "<", "<=", "==", "!=", "in", "exists"]
    value: Any = None


Condition = Always | AllOf | AnyOf | Negation | Comparison


class FactRef(Value):
    ref: str


class ShiftAction(Value):
    op: Literal["shift"]
    param: str
    delta: float


class BoundAction(Value):
    """Границы самого параметра t."""

    op: Literal["bound"]
    param: str
    min_t: float | None = None
    max_t: float | None = None


class LimitAction(Value):
    op: Literal["limit"]
    param: str
    minimum: NumberSpec | None = Field(default=None, alias="min")
    maximum: NumberSpec | None = Field(default=None, alias="max")


class StartAction(Value):
    """Начальное значение оси вместо слайсера."""

    op: Literal["start"]
    param: str
    value: NumberSpec


class MinLayersAction(Value):
    op: Literal["min_layers"]
    param: str
    minimum: int = Field(alias="min")


class SetDiscreteAction(Value):
    op: Literal["set_discrete"]
    param: str
    value: bool | str


class ModeVoteAction(Value):
    op: Literal["mode_vote"]
    mode: str | FactRef
    weight: float


class UnsatisfiedAction(Value):
    op: Literal["unsatisfied"]
    requirement_key: str
    why: str


Action = Annotated[
    ShiftAction
    | BoundAction
    | LimitAction
    | StartAction
    | MinLayersAction
    | SetDiscreteAction
    | ModeVoteAction
    | UnsatisfiedAction,
    Field(discriminator="op"),
]


class Rule(Value):
    # шаблон идентификатора правила
    id: Annotated[str, StringConstraints(pattern=r"^[\w\-.]+$")]
    source: Annotated[str, StringConstraints(min_length=1)]
    reason: Annotated[str, StringConstraints(min_length=1)]
    when: Condition
    then: list[Action]


class RuleBook(Value):
    note: str
    rules: list[Rule]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> RuleBook:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self


for _model in (AllOf, AnyOf, Negation):
    _model.model_rebuild()

RULES = RuleBook.model_validate_json(
    Path(__file__).with_name("rules.json").read_text(encoding="utf-8")
).rules
RULE_BY_ID = {rule.id: rule for rule in RULES}
REASONS = {rule.id: rule.reason for rule in RULES}

_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def holds(condition: Condition, facts: Facts) -> bool:
    """Выполняется ли условие правила."""
    if isinstance(condition, Always):
        return True
    if isinstance(condition, AllOf):
        return all(holds(item, facts) for item in condition.all)
    if isinstance(condition, AnyOf):
        return any(holds(item, facts) for item in condition.any)
    if isinstance(condition, Negation):
        return not holds(condition.negated, facts)
    return _compares(condition, facts)


def _compares(comparison: Comparison, facts: Facts) -> bool:
    if comparison.op == "exists":
        return comparison.fact in facts
    if comparison.fact not in facts:
        return False
    left = facts[comparison.fact]
    if comparison.op == "in":
        return left in comparison.value
    return _COMPARISONS[comparison.op](left, comparison.value)


def fired_rules(facts: Facts) -> list[Rule]:
    return [rule for rule in RULES if holds(rule.when, facts)]


def vote_mode(spec: str | FactRef, facts: Facts) -> str:
    """Режим из литерала или факта."""
    if isinstance(spec, FactRef):
        return str(facts[spec.ref])
    return spec


def requirement_keys(rule: Rule) -> list[str]:
    """Коды требований, читаемые правилом."""
    found = set()
    for comparison in _comparisons(rule.when):
        prefix, _, key = comparison.fact.partition(".")
        if prefix in ("req", "reqhard"):
            found.add(key)
    return sorted(found)


def _comparisons(condition: Condition) -> Iterator[Comparison]:
    if isinstance(condition, Comparison):
        yield condition
        return
    for child in _children(condition):
        yield from _comparisons(child)


def _children(condition: Condition) -> list[Condition]:
    if isinstance(condition, AllOf):
        return condition.all
    if isinstance(condition, AnyOf):
        return condition.any
    if isinstance(condition, Negation):
        return [condition.negated]
    return []


def reason(rule_id: str | None) -> str:
    """Причина значения для пользователя."""
    if rule_id is None:
        return "значение слайсера"
    if rule_id.startswith("constraint:"):
        return f"ограничение этапа 3 ({rule_id})"
    return REASONS.get(rule_id, rule_id)


def source_of(rule_id: str | None) -> str:
    """Источник значения настройки слайсера."""
    if rule_id is None:
        return "default"
    if ":" in rule_id:
        return rule_id
    return f"rule:{rule_id}"
