from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..domain.models import Requirement, Value
from ..domain.requirement_keys import RequirementKey, RequirementKeys


class _Lexicon(Value):
    note: str
    codes: list[dict[str, list[str] | str]]
    chemical_context: list[str]
    chemical_media: dict[str, list[str]]


_LEXICON = _Lexicon.model_validate_json(
    Path(__file__).with_name("free_keys.json").read_text(encoding="utf-8")
)
CHEMICALS = "chemical_resistance"


@dataclass(frozen=True)
class _Pattern:
    code: str
    match: tuple[re.Pattern[str], ...]
    veto: tuple[re.Pattern[str], ...]

    def reads(self, text: str) -> bool:
        return any(p.search(text) for p in self.match) and not any(
            p.search(text) for p in self.veto
        )


_PATTERNS = tuple(
    _Pattern(
        str(entry["code"]),
        tuple(re.compile(p) for p in entry["match"]),
        tuple(re.compile(p) for p in entry.get("not", [])),
    )
    for entry in _LEXICON.codes
)
_CONTEXT = tuple(re.compile(p) for p in _LEXICON.chemical_context)
_MEDIA = {
    medium: tuple(re.compile(p) for p in found) for medium, found in _LEXICON.chemical_media.items()
}


@dataclass(frozen=True)
class Reading:
    """Требование карточки как код."""

    requirement_id: str
    code: str
    value: float | bool | tuple[str, ...]
    hard: bool
    source: Requirement


@dataclass
class Translation:
    readings: list[Reading] = field(default_factory=list)
    # прочитанные требования
    used: set[str] = field(default_factory=set)


NumberReader = Callable[[Requirement, RequirementKey], float]


def text_of(requirement: Requirement) -> str:
    return " ".join(
        part for part in (requirement.key, requirement.label, requirement.value) if part
    ).lower()


def quotes_of(requirement: Requirement) -> str:
    return " ".join(source.quote for source in requirement.sources if source.quote).lower()


def translate(
    free: Sequence[tuple[Requirement, str]],
    keys: RequirementKeys,
    skipped: set[str],
    read_number: NumberReader,
) -> Translation:
    """Коды из свободных требований карточки."""
    found = Translation()
    numbers: dict[str, list[Reading]] = {}
    media: list[str] = []
    media_sources: list[tuple[Requirement, str]] = []
    for requirement, requirement_id in free:
        text = text_of(requirement)
        reading = _first_reading(text, requirement, requirement_id, keys, skipped, read_number)
        if reading is not None:
            _keep(found, numbers, reading)
        if CHEMICALS not in skipped and any(p.search(text) for p in _CONTEXT):
            named = _media(f"{text} {quotes_of(requirement)}")
            if named:
                media.extend(medium for medium in named if medium not in media)
                media_sources.append((requirement, requirement_id))
                found.used.add(requirement_id)
    for code, readings in numbers.items():
        found.readings.append(_binding(code, readings, keys))
    if media:
        first, first_id = media_sources[0]
        hard = any(requirement.mandatory for requirement, _ in media_sources)
        found.readings.append(Reading(first_id, CHEMICALS, tuple(media), hard, first))
    return found


def _keep(found: Translation, numbers: dict[str, list[Reading]], reading: Reading) -> None:
    """Более строгий конец побеждает."""
    if isinstance(reading.value, float):
        numbers.setdefault(reading.code, []).append(reading)
    elif reading.code not in {kept.code for kept in found.readings}:
        found.readings.append(reading)
    found.used.add(reading.requirement_id)


def _first_reading(
    text: str,
    requirement: Requirement,
    requirement_id: str,
    keys: RequirementKeys,
    skipped: set[str],
    read_number: NumberReader,
) -> Reading | None:
    """Первый подходящий код словаря."""
    for pattern in _PATTERNS:
        if pattern.code in skipped or not pattern.reads(text):
            continue
        reading = _read(pattern.code, requirement, requirement_id, keys, read_number)
        if reading is not None:
            return reading
    return None


def _read(
    code: str,
    requirement: Requirement,
    requirement_id: str,
    keys: RequirementKeys,
    read_number: NumberReader,
) -> Reading | None:
    entry = keys.get(code)
    if entry is None:
        return None
    hard = requirement.mandatory
    if entry.kind == "number":
        try:
            value = read_number(requirement, entry)
        except ValueError:
            return None
        return Reading(requirement_id, code, float(value), hard, requirement)
    if entry.kind == "flag":
        return Reading(requirement_id, code, True, hard, requirement)
    return None


def _binding(code: str, readings: Sequence[Reading], keys: RequirementKeys) -> Reading:
    """Строгий конец числового кода."""
    entry = keys.get(code)
    strict = entry.strict if entry is not None else None
    pick = max if strict == "upper" else min
    chosen = pick(readings, key=lambda reading: Decimal(str(reading.value)))
    return Reading(
        chosen.requirement_id,
        code,
        chosen.value,
        any(reading.hard for reading in readings),
        chosen.source,
    )


def _media(text: str) -> list[str]:
    return [medium for medium, found in _MEDIA.items() if any(p.search(text) for p in found)]
