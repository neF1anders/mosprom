"""Deterministic readiness gates. Model output cannot declare itself ready."""

from __future__ import annotations

from .models import SELECT_PARAMETERS, TaskCard

RULES_VERSION = "5"
UNKNOWN = {"", "не знаю", "unknown", "неизвестно"}
# The one spelling of "unknown" stored and shown; the interface checks only this value.
UNKNOWN_ANSWER = "Не знаю"


def known(value: str | None) -> bool:
    return value is not None and value.strip().casefold() not in UNKNOWN


def canonical(value: str) -> str:
    return value.strip() if known(value) else UNKNOWN_ANSWER


def assess(card: TaskCard, failed_files: list[str]) -> TaskCard:
    blockers: list[str] = []
    if card.geometry is None or not card.geometry.readable:
        blockers.append("Нужна читаемая модель STL")
    blockers.extend(q.title for q in card.questions if q.blocking and not known(q.answer))
    if failed_files:
        blockers.append("Не прочитаны файлы " + ", ".join(failed_files))
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
