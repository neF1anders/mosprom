from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import Conflict, Evidence, Question, Requirement, TaskCard
from .rules import known, normalize_quantity


def validate_evidence(card: TaskCard, sources: dict[str, dict]) -> TaskCard:
    """O(total citation text): quoted evidence, not model confidence, establishes provenance."""
    normalized = {key: " ".join(source.get("text", "").split()) for key, source in sources.items()}
    for requirement in card.requirements:
        valid = bool(requirement.sources)
        quoted_numbers: set[str] = set()
        for evidence in requirement.sources:
            source = sources.get(evidence.source_id, {})
            quote = " ".join(evidence.quote.split())
            text = normalized.get(evidence.source_id, "")
            quoted_numbers.update(numbers(quote))
            page_valid = evidence.page is None or evidence.page == source.get("page")
            valid = (
                valid
                and bool(quote)
                and quote in text
                and not source.get("uncertain", False)
                and page_valid
            )
        requirement.verified = (
            requirement.verified
            and valid
            and numbers(requirement.value).issubset(quoted_numbers)
            and requirement.provenance != "assumption"
        )
        if requirement.mandatory and not requirement.verified:
            key = verification_id(requirement)
            card.questions.append(
                Question(
                    id=key,
                    title=f"Уточните требование {requirement.label or requirement.key}",
                    reason=f"Не удалось подтвердить значение {requirement.value} по источнику",
                    options=[requirement.value] if requirement.sources else [],
                )
            )
    return card


def _conflicts(requirements: list[Requirement]) -> list[Conflict]:
    # One conflict per comparable property, rather than all O(n²) pairs of values.
    groups: dict[tuple, dict[tuple, Requirement]] = defaultdict(dict)
    for requirement in requirements:
        value, unit = normalize_quantity(requirement.value, requirement.unit or "")
        key = (requirement.key, requirement.conditions.strip().casefold(), unit)
        groups[key][(value, unit)] = requirement
    conflicts = []
    for key, alternatives in groups.items():
        if len(alternatives) < 2:
            continue
        identity = hashlib.sha256(str((key, sorted(alternatives))).encode()).hexdigest()[:16]
        values = list(alternatives.values())
        conflicts.append(
            Conflict(
                id=identity,
                title=values[0].label or key[0],
                options=[f"{r.value} {r.unit or ''}".strip() for r in values],
                sources=[source for r in values for source in r.sources],
            )
        )
    return conflicts


def merge_cards(cards: list[TaskCard]) -> TaskCard:
    result = TaskCard()
    seen: set[tuple] = set()
    for card in cards:
        result.purpose = card.purpose or result.purpose
        for field in (
            "preferences",
            "assumptions",
            "unknowns",
            "questions",
            "conflicts",
            "production_constraints",
        ):
            getattr(result, field).extend(getattr(card, field))
        for requirement in card.requirements:
            identity = (
                requirement.key,
                requirement.value,
                requirement.unit,
                requirement.conditions,
            )
            if identity not in seen:
                seen.add(identity)
                result.requirements.append(requirement)
    result.conflicts.extend(_conflicts(result.requirements))
    result.questions = list({q.id: q for q in result.questions}.values())
    result.conflicts = list({c.id: c for c in result.conflicts}.values())
    for field in ("preferences", "assumptions", "unknowns", "production_constraints"):
        setattr(result, field, list(dict.fromkeys(getattr(result, field))))
    return result


def verification_id(requirement: Requirement) -> str:
    return (
        "verify." + hashlib.sha256((requirement.key + requirement.value).encode()).hexdigest()[:16]
    )


def apply_answers(
    card: TaskCard, answers: dict[str, str], resolutions: dict[str, str], source_id: str
) -> None:
    """Only persisted user commands can confirm or replace a requirement."""
    for requirement in card.requirements:
        key = verification_id(requirement)
        answer = answers.get(key)
        if answer is None or not known(answer):
            continue
        requirement.value = answer
        requirement.verified = True
        requirement.provenance = "user"
        requirement.sources = [Evidence(source_id=source_id, quote=f"{key} = {answer}")]
    for conflict in card.conflicts:
        conflict.resolution = resolutions.get(conflict.id)
        conflict.resolved = known(conflict.resolution)


def numbers(text: str) -> set[str]:
    return {
        normalize_quantity(value, "")[0] for value in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", text)
    }
