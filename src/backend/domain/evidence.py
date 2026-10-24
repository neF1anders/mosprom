"""Algorithmic guardrails over requirements: citations, reconciliation, user decisions."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from .hashing import digest
from .models import Evidence, Question, Requirement, Source, Superseded
from .rules import known
from .units import numbers, plain, quantity_key, restated

METHOD = {"message": "user", "answer": "user", "document": "text", "knowledge": "knowledge"}
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "ё": "е", "«": '"', "»": '"'})
_AMOUNT = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(\S.*)?$")
Citation = Literal["verified", "vision", "rejected"]


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().translate(_DASHES).split())


def reference(requirement: Requirement) -> str:
    return digest(requirement.key, normalize_text(requirement.conditions))


def display(requirement: Requirement) -> str:
    return f"{requirement.value} {requirement.unit or ''}".strip()


def check_citations(requirement: Requirement, sources: dict[str, Source]) -> Citation:
    """Text must be quoted literally; image-only readings need an independent second reading.

    The value's numbers must be in the quote, as they are or converted to the requirement's
    unit from the unit the quote names.
    """
    if requirement.provenance == "assumption" or not requirement.sources:
        return "rejected"
    pending, quoted = False, set[str]()
    for evidence in requirement.sources:
        source = sources.get(evidence.source_id)
        if source is None or not evidence.quote.strip():
            return "rejected"
        if None not in (evidence.page, source.page) and evidence.page != source.page:
            return "rejected"
        evidence.page, evidence.artifact_id = source.page, source.image
        quoted.update(plain(n) for n in numbers(evidence.quote))
        quoted.update(plain(n) for n in restated(evidence.quote, requirement.unit))
        if normalize_text(evidence.quote) in normalize_text(source.text):
            evidence.method = METHOD[source.kind]  # type: ignore[assignment]
        elif source.image:
            evidence.method, pending = "vision", True
        else:
            return "rejected"
    if not {plain(n) for n in numbers(requirement.value)} <= quoted:
        return "rejected"
    return "vision" if pending else "verified"


def verify_question(requirement: Requirement, impact: str, options: list[str]) -> Question:
    return Question(
        id="verify." + reference(requirement),
        kind="verify",
        title=f"Уточните {requirement.label or requirement.key}",
        impact=impact,
        options=list(dict.fromkeys(o for o in options if o)),
        sources=requirement.sources,
        requirement_key=requirement.key,
    )


def same_quantity(requirement: Requirement, value: str, unit: str | None) -> bool:
    return quantity_key(requirement.value, requirement.unit) == quantity_key(value, unit)


def apply_decision(
    requirement: Requirement, question_id: str, answer: str, alternatives: list[Requirement]
) -> Requirement:
    """A user's choice replaces the value; every other stated value is kept as history."""
    chosen = next((a for a in alternatives if display(a) == answer.strip()), None)
    value, unit = (chosen.value, chosen.unit) if chosen else _parse(answer, requirement.unit)
    result = requirement.model_copy(
        deep=True,
        update={
            "value": value,
            "unit": unit,
            "verified": True,
            "provenance": "user",
            "sources": [Evidence(source_id=f"answer:{question_id}", quote=answer, method="user")],
        },
    )
    result.superseded.extend(
        Superseded(
            value=a.value, unit=a.unit, sources=a.sources, reason="Отклонено решением пользователя"
        )
        for a in alternatives
        if not same_quantity(result, a.value, a.unit)
    )
    return result


def _parse(answer: str, unit: str | None) -> tuple[str, str | None]:
    match = _AMOUNT.match(answer)
    if match is None:
        return answer.strip(), None
    return match.group(1), match.group(2) or unit


def reconcile(
    requirements: list[Requirement], sources: dict[str, Source], answers: dict[str, str]
) -> tuple[list[Requirement], list[Question]]:
    """One value per property: user statements win, documents that disagree go to the user."""
    groups: dict[str, list[Requirement]] = {}
    for requirement in requirements:
        groups.setdefault(reference(requirement), []).append(requirement)
    result, questions = [], []
    for ref, members in groups.items():
        distinct = _distinct(members)
        if len(distinct) == 1:
            result.append(distinct[0])
            continue
        from_user = [m for m in distinct if _stated_by_user(m, sources)]
        if from_user:
            winner = max(from_user, key=lambda m: _newest(m, sources))
            winner.superseded.extend(
                Superseded(
                    value=m.value,
                    unit=m.unit,
                    sources=m.sources,
                    reason="Заменено сообщением пользователя",
                )
                for m in distinct
                if m is not winner
            )
            result.append(winner)
            continue
        question = Question(
            id="sources." + ref,
            kind="discrepancy",
            title=f"Источники расходятся, {distinct[0].label or distinct[0].key}",
            impact="Влияет на подбор параметров",
            options=[display(m) for m in distinct],
            sources=[e for m in distinct for e in m.sources],
            requirement_key=distinct[0].key,
        )
        answer = answers.get(question.id, "")
        if known(answer):
            result.append(apply_decision(distinct[0], question.id, answer, distinct))
        else:
            result.append(distinct[0].model_copy(update={"verified": False}))
        questions.append(question)
    return result, questions


def _distinct(members: list[Requirement]) -> list[Requirement]:
    unique: dict[tuple, Requirement] = {}
    for member in sorted(members, key=lambda m: not m.verified):
        primary = unique.setdefault(quantity_key(member.value, member.unit), member)
        if primary is not member:
            primary.sources.extend(e for e in member.sources if e.method is not None)
    return list(unique.values())


def _stated_by_user(requirement: Requirement, sources: dict[str, Source]) -> bool:
    return any(
        e.method == "user" and sources[e.source_id].kind in {"message", "answer"}
        for e in requirement.sources
        if e.source_id in sources
    )


def _newest(requirement: Requirement, sources: dict[str, Source]) -> datetime:
    times = [
        sources[e.source_id].created_at or datetime.min.replace(tzinfo=timezone.utc)
        for e in requirement.sources
        if e.method == "user" and e.source_id in sources
    ]
    return max(times)
