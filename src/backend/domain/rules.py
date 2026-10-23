"""Deterministic readiness gates. Model output cannot declare itself ready."""

from __future__ import annotations

from .models import SELECT_PARAMETERS, Geometry, Question, TaskCard
from .units import STL_UNITS

RULES_VERSION = "4"
UNKNOWN = {"", "не знаю", "unknown", "неизвестно"}


def known(value: str | None) -> bool:
    return value is not None and value.strip().casefold() not in UNKNOWN


def units_question(geometry: Geometry) -> Question:
    size = " × ".join(f"{x:g}" for x in geometry.extents)
    return Question(
        id="units",
        kind="units",
        title="В каких единицах создан STL",
        impact=f"Габариты в единицах файла {size}, от масштаба зависят размеры и параметры печати",
        options=list(STL_UNITS),
    )


def purpose_question() -> Question:
    return Question(
        id="purpose",
        kind="purpose",
        title="Для чего нужна деталь",
        impact="Назначение определяет требования к материалу и параметрам",
    )


def assess(card: TaskCard, failed_files: list[str]) -> TaskCard:
    blockers: list[str] = []
    if card.geometry is None or not card.geometry.readable:
        blockers.append("Нужна читаемая модель STL")
    if any(r.mandatory and not r.verified for r in card.requirements):
        blockers.append("Есть неподтверждённые обязательные требования")
    blockers.extend(q.title for q in card.questions if q.blocking and not known(q.answer))
    if failed_files:
        blockers.append("Не прочитаны файлы " + ", ".join(failed_files))
    if card.verdict is not None and not card.verdict.passed:
        blockers.append("Интерпретация не прошла итоговую проверку")
    card.blocked_actions = {SELECT_PARAMETERS: list(dict.fromkeys(blockers))} if blockers else {}
    card.allowed_actions = [] if blockers else [SELECT_PARAMETERS]
    card.readiness = "blocked" if blockers else "ready"
    if not blockers and _caveats(card):
        card.readiness = "preliminary"
    return card


def _caveats(card: TaskCard) -> bool:
    return bool(
        card.assumptions
        or card.unknowns
        or (card.geometry is not None and card.geometry.defects)
        or any(not known(q.answer) for q in card.questions)
    )
