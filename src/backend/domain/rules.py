"""Deterministic gates. LLM output cannot declare itself ready."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from .catalog import GATES, RULES_VERSION
from .models import CARD_SCHEMA_VERSION, Question, Requirement, TaskCard

UNKNOWN = {"", "не знаю", "unknown", "неизвестно"}
UNITS = {"mm", "cm", "m", "inch"}
# These names refer to the same STL coordinate-unit fact, never a material property.
QUESTION_ALIASES = dict.fromkeys(
    ["model_units", "stl_units", "geometry_units", "stl.units", "model_unit", "stl_unit"],
    "geometry.units",
)
CONVERSIONS = {
    "cm": ("10", "mm"),
    "m": ("1000", "mm"),
    "inch": ("25.4", "mm"),
    "g/cm3": ("1000", "kg/m3"),
}


def known(value: str | None) -> bool:
    return value is not None and value.strip().casefold() not in UNKNOWN


def normalize_quantity(value: str, unit: str) -> tuple[str, str]:
    unit = {"мм": "mm", "см": "cm", "м": "m", "г/см³": "g/cm3", "кг/м³": "kg/m3"}.get(unit, unit)
    value = value.strip()
    if unit and value.endswith(unit):
        value = value[: -len(unit)].strip()
    factor, target = CONVERSIONS.get(unit, ("1", unit))
    try:
        result = Decimal(value.replace(",", ".")) * Decimal(factor)
    except InvalidOperation:
        return value, unit
    return format(result.normalize(), "f"), target


def comparable(left: Requirement, right: Requirement) -> bool:
    return (
        left.key == right.key
        and left.conditions.strip().casefold() == right.conditions.strip().casefold()
    )


def assess(card: TaskCard, answers: dict[str, str] | None = None) -> TaskCard:
    card = card.model_copy(deep=True)
    card.rules_version = RULES_VERSION
    card.schema_version = CARD_SCHEMA_VERSION
    card.knowledge_version = "kb001-v1"
    answers = answers or {}
    questions = {
        QUESTION_ALIASES.get(q.id, q.id): q.model_copy(
            update={"id": QUESTION_ALIASES.get(q.id, q.id)}
        )
        for q in card.questions
    }
    blocked: dict[str, list[str]] = {"select_parameters": []}
    for gate in GATES:
        if not gate.satisfied(card):
            _block(blocked, [gate.action], gate.reason)
    _geometry_gate(card, questions, blocked)
    if not card.purpose.strip():
        questions["purpose"] = Question(
            id="purpose",
            title="Для чего нужна деталь?",
            reason="Назначение определяет требования к материалу",
            affected_actions=["assess_materials", "select_parameters"],
        )
    for conflict in card.conflicts:
        conflict.resolved = known(conflict.resolution)
        if not conflict.resolved:
            _block(blocked, ["select_parameters", *conflict.affected_actions], conflict.title)
    for question in questions.values():
        question.answer = answers.get(question.id)
        if not known(question.answer):
            _block(blocked, ["select_parameters", *question.affected_actions], question.reason)
    card.questions = list(questions.values())
    card.blocked_actions = {
        action: list(dict.fromkeys(reasons)) for action, reasons in blocked.items() if reasons
    }
    card.allowed_actions = [
        a
        for a in ["interpret_requirements", "assess_materials", "select_parameters"]
        if a not in card.blocked_actions
    ]
    card.readiness = _readiness(card)
    return card


def _block(blocked: dict[str, list[str]], actions: list[str], reason: str) -> None:
    for action in actions:
        reasons = blocked.setdefault(action, [])
        reasons.append(reason)


def _geometry_gate(
    card: TaskCard, questions: dict[str, Question], blocked: dict[str, list[str]]
) -> None:
    geometry = card.geometry
    if geometry.units not in UNITS:
        questions["geometry.units"] = Question(
            id="geometry.units",
            title="В каких единицах создан STL?",
            reason="Масштаб нужен для физических размеров и параметров печати",
            options=["mm", "cm", "m", "inch"],
        )
    else:
        questions.pop("geometry.units", None)
    if geometry.defects:
        geometry.physical_volume_confirmed = False


def _readiness(card: TaskCard) -> Literal["ready", "preliminary", "blocked"]:
    if "select_parameters" not in card.allowed_actions:
        return "blocked"
    if card.assumptions or card.unknowns or card.geometry.defects:
        return "preliminary"
    return "ready"
