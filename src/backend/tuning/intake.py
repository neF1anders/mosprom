"""Stage-one task card (``TaskCard`` 2.0) -> what parameter selection reads from it.

Requirement codes, kinds and units come from the dictionary shared with stage one
(``knowledge/requirement_keys.json``); a requirement under another key, or under a code no step
of the selection reads, is reported as not taken into account. Free text is read only for a ban
on supports, the load and, when the card has no ``priority`` code, the priorities, by the
phrases of ``phrases.json``; every such inference is told to the user as an assumption.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal

from ..domain.errors import AppError
from ..domain.models import CARD_SCHEMA_VERSION, SELECT_PARAMETERS, Requirement, TaskCard, Value
from ..domain.requirement_keys import RequirementKey, RequirementKeys
from ..domain.units import convert, dimension, numbers
from .geometry import Geometry, read_geometry

RequirementValue = float | bool | str | tuple[str, ...]
# How far a requirement is confirmed: by the user or a document, by knowledge, or not at all.
Basis = Literal["user", "model", "assumption"]
_BASIS: dict[str, Basis] = {
    "user": "user",
    "document": "user",
    "knowledge": "model",
    "assumption": "assumption",
}
_LIST_SEPARATORS = re.compile(r"[,;]")
# Codes that describe the part rather than demand anything of the print: when no step reads
# them there is nothing to tell the user, only the log.
_DESCRIPTIVE = frozenset({"part_class"})


class _Booleans(Value):
    true: list[str]
    false: list[str]


class Phrases(Value):
    note: str
    booleans: _Booleans
    load_phrases: list[tuple[str, list[str]]]
    priority_phrases: dict[str, list[str]]
    supports_forbidden_phrases: list[str]


PHRASES = Phrases.model_validate_json(
    Path(__file__).with_name("phrases.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class CardRequirement:
    id: str
    key: str
    value: RequirementValue
    hard: bool
    basis: Basis


@dataclass(frozen=True)
class MaterialRequest:
    """A material named by the card, an answer or a check constraint, with that origin."""

    name: str
    source: str


@dataclass(frozen=True)
class ModeRequest:
    mode: str
    requirement_id: str


@dataclass(frozen=True)
class TuningInput:
    job_id: str
    revision: int
    attachment_id: str
    geometry: Geometry
    requirements: tuple[CardRequirement, ...]
    priority: tuple[str, ...]
    supports_allowed: bool
    quantity: int
    load: str | None
    mode: ModeRequest | None
    material: MaterialRequest | None
    # Told to the user (stage-one assumptions and what this reading inferred) and to the logs.
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]


class Unreadable(ValueError):
    """A requirement value cannot be read as the kind its code has."""


@dataclass
class _Draft:
    """What the card has said so far; frozen into ``TuningInput`` once the card is read."""

    assumptions: list[str]
    requirements: list[CardRequirement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quantity: int = 1
    priority: tuple[str, ...] = ()
    load: str | None = None
    mode: ModeRequest | None = None
    material: MaterialRequest | None = None


def read_card(card: TaskCard, keys: RequirementKeys, read: Collection[str]) -> TuningInput:
    """``read``: the codes a step of the selection reads besides the card fields below."""
    draft = _Draft(assumptions=_readiness_notes(card))
    for requirement, requirement_id in _with_ids(card.requirements):
        _read_requirement(draft, requirement, requirement_id, keys, read)
    wishes = " ".join(text for text in card.preferences if text).lower()
    priority = _priority(draft, wishes)
    supports_allowed = _supports_allowed(draft, wishes)
    if draft.load is None:
        _read_production_load(draft, card.production_constraints)
    draft.assumptions.extend(assumption.text for assumption in card.assumptions)
    draft.warnings.extend(f"stage 1 unknown: {text}" for text in card.unknowns)
    reading = read_geometry(card.stl_analysis)
    return TuningInput(
        job_id=card.job_id,
        revision=card.revision,
        attachment_id=reading.attachment_id,
        geometry=reading.geometry,
        requirements=tuple(draft.requirements),
        priority=priority,
        supports_allowed=supports_allowed,
        quantity=draft.quantity,
        load=draft.load,
        mode=draft.mode,
        material=draft.material,
        assumptions=(*draft.assumptions, *reading.assumptions),
        warnings=(*draft.warnings, *reading.warnings),
    )


def stricter_end(text: str, strict: Literal["upper", "lower"] | None) -> Decimal:
    """A single number, or the binding end of a two-number range."""
    found = numbers(text)
    if len(found) == 1:
        return found[0]
    if len(found) == 2:
        return max(found) if strict == "upper" else min(found)
    raise Unreadable(f"expected a number or a range, got {text!r}")


def read_flag(text: str) -> bool:
    """An exact yes or no from the phrase list; anything else is ambiguous."""
    normalized = text.strip().lower()
    if normalized in PHRASES.booleans.false:
        return False
    if normalized in PHRASES.booleans.true:
        return True
    raise Unreadable(f"expected yes/no, got {text!r}")


def _readiness_notes(card: TaskCard) -> list[str]:
    """Refuse a card stage one does not release; a preliminary one is used with a caveat."""
    if card.schema_version != CARD_SCHEMA_VERSION:
        raise AppError(
            f"Карточка версии {card.schema_version}, подбор параметров читает {CARD_SCHEMA_VERSION}",
            "card_schema",
        )
    blocked = card.blocked_actions.get(SELECT_PARAMETERS, [])
    if card.readiness == "blocked" or blocked:
        reasons = "; ".join(blocked) or "карточка не готова"
        raise AppError(f"Этап 1 не разрешил подбор параметров. {reasons}", "card_blocked")
    if card.readiness == "preliminary":
        return [f"карточка предварительная (ревизия {card.revision}): результат может измениться"]
    return []


def _with_ids(requirements: Sequence[Requirement]) -> Iterator[tuple[Requirement, str]]:
    """The requirement code is its id; a repeated code gets ``key-2``, ``key-3`` and so on."""
    seen: dict[str, int] = {}
    for requirement in requirements:
        key = requirement.key or "unnamed"
        seen[key] = seen.get(key, 0) + 1
        yield requirement, key if seen[key] == 1 else f"{key}-{seen[key]}"


def _read_requirement(
    draft: _Draft,
    requirement: Requirement,
    requirement_id: str,
    keys: RequirementKeys,
    read: Collection[str],
) -> None:
    label = f"{requirement_id} ({requirement.label or requirement.key})"
    entry = keys.get(requirement.key)
    if entry is None:
        _not_interpreted(draft, requirement, label)
        return
    card_field = _CARD_FIELDS.get(entry.key)
    if card_field is not None:
        card_field(draft, requirement, requirement_id, label, entry)
        return
    reader = _VALUES.get(entry.kind)
    if reader is None or entry.key not in read:
        _not_interpreted(draft, requirement, label)
        return
    try:
        value = reader(requirement, entry)
    except Unreadable as error:
        _not_interpreted(draft, requirement, f"{label}: {error}")
        return
    draft.requirements.append(
        CardRequirement(
            requirement_id, entry.key, value, requirement.mandatory, _basis(requirement)
        )
    )


def _basis(requirement: Requirement) -> Basis:
    if not requirement.verified:
        return "assumption"
    return _BASIS.get(requirement.provenance, "assumption")


def _not_interpreted(draft: _Draft, requirement: Requirement, label: str) -> None:
    if requirement.mandatory and requirement.key not in _DESCRIPTIVE:
        draft.assumptions.append(f"обязательное требование {label} не учтено подбором параметров")
    else:
        draft.warnings.append(f"requirement {label} is not used by parameter selection")


def _number(requirement: Requirement, entry: RequirementKey) -> float:
    """The binding end of the stated range, in the unit of the code."""
    unit, expected = requirement.unit, entry.unit or ""
    if unit is None or dimension(unit) is None or dimension(unit) != dimension(expected):
        raise Unreadable(f"unit {unit!r}, expected {entry.unit}")
    return float(convert(stricter_end(requirement.value, entry.strict), unit, expected))


def _flag(requirement: Requirement, entry: RequirementKey) -> bool:
    return read_flag(requirement.value)


def _items(requirement: Requirement, entry: RequirementKey) -> tuple[str, ...]:
    items = [item.strip().lower() for item in _LIST_SEPARATORS.split(requirement.value)]
    found = tuple(item for item in items if item)
    if not found:
        raise Unreadable(f"expected a list, got {requirement.value!r}")
    return found


def _read_quantity(
    draft: _Draft, requirement: Requirement, requirement_id: str, label: str, entry: RequirementKey
) -> None:
    try:
        draft.quantity = int(stricter_end(requirement.value, entry.strict))
    except Unreadable as error:
        draft.warnings.append(f"quantity {label}: {error}")


def _read_load(
    draft: _Draft, requirement: Requirement, requirement_id: str, label: str, entry: RequirementKey
) -> None:
    code = requirement.value.strip().lower()
    if code in entry.options:
        draft.load = code
        _note_unconfirmed(
            draft,
            requirement,
            f"нагрузка «{code}» в карточке не подтверждена и принята как допущение",
        )
        return
    _set_load(draft, requirement.value, label)


def _read_printing_mode(
    draft: _Draft, requirement: Requirement, requirement_id: str, label: str, entry: RequirementKey
) -> None:
    mode = requirement.value.strip().lower()
    if mode in entry.options:
        draft.mode = ModeRequest(mode, requirement_id)
        _note_unconfirmed(
            draft,
            requirement,
            f"режим печати {mode} в карточке не подтверждён и принят как допущение",
        )
        return
    draft.warnings.append(
        f"printing mode {requirement_id} is not one of {', '.join(entry.options)}"
    )


def _read_priority(
    draft: _Draft, requirement: Requirement, requirement_id: str, label: str, entry: RequirementKey
) -> None:
    """Known priorities in the stated order; an unknown one is dropped with a warning. Without
    a known one the wishes are read instead."""
    options = ", ".join(entry.options)
    items = [item.strip().lower() for item in _LIST_SEPARATORS.split(requirement.value)]
    known = tuple(dict.fromkeys(item for item in items if item in entry.options))
    if not known:
        _not_interpreted(
            draft, requirement, f"{label}: expected some of {options}, got {requirement.value!r}"
        )
        return
    unknown = [item for item in items if item and item not in entry.options]
    if unknown:
        draft.warnings.append(f"priority {label}: {', '.join(unknown)} not one of {options}")
    draft.priority = known
    _note_unconfirmed(
        draft,
        requirement,
        f"приоритеты {', '.join(known)} в карточке не подтверждены и приняты как допущение",
    )


def _note_unconfirmed(draft: _Draft, requirement: Requirement, text: str) -> None:
    """A card field taken from an unconfirmed requirement is told to the user as an assumption."""
    if _basis(requirement) == "assumption":
        draft.assumptions.append(text)


def _read_material(
    draft: _Draft, requirement: Requirement, requirement_id: str, label: str, entry: RequirementKey
) -> None:
    if _basis(requirement) == "assumption":
        draft.warnings.append(f"material {label} is not confirmed, catalog ranking is used")
        return
    if requirement.value:
        draft.material = MaterialRequest(requirement.value, f"requirement:{requirement_id}")


_CardField = Callable[[_Draft, Requirement, str, str, RequirementKey], None]
_CARD_FIELDS: dict[str, _CardField] = {
    "quantity": _read_quantity,
    "priority": _read_priority,
    "load_bearing": _read_load,
    "printing_mode": _read_printing_mode,
    "material": _read_material,
}
_VALUES: dict[str, Callable[[Requirement, RequirementKey], RequirementValue]] = {
    "number": _number,
    "flag": _flag,
    "list": _items,
}


def _first_match(phrases: Sequence[str], text: str) -> int | None:
    """Where the earliest phrase of ``phrases.json`` is found in the lowercase text, if any."""
    found = [match.start() for phrase in phrases if (match := re.search(phrase, text))]
    return min(found, default=None)


def _set_load(draft: _Draft, text: str, origin: str) -> None:
    lowered = text.lower()
    for load, phrases in PHRASES.load_phrases:
        if _first_match(phrases, lowered) is not None:
            draft.load = load
            draft.assumptions.append(f"нагрузка «{load}» выведена из текста: {origin}")
            return
    draft.warnings.append(f"load of {origin} not recognised: {text!r}")


def _priority(draft: _Draft, wishes: str) -> tuple[str, ...]:
    """The ``priority`` code of the card, else priorities in the order the wishes name them."""
    if draft.priority:
        return draft.priority
    positions = []
    for priority, phrases in sorted(PHRASES.priority_phrases.items()):
        first = _first_match(phrases, wishes)
        if first is not None:
            positions.append((first, priority))
    found = tuple(priority for _, priority in sorted(positions))
    if found:
        draft.assumptions.append(f"приоритеты {', '.join(found)} выведены из текста пожеланий")
    return found


def _supports_allowed(draft: _Draft, wishes: str) -> bool:
    if _first_match(PHRASES.supports_forbidden_phrases, wishes) is not None:
        draft.assumptions.append("поддержки запрещены по тексту пожеланий")
        return False
    return True


def _read_production_load(draft: _Draft, constraints: Sequence[str]) -> None:
    for constraint in constraints:
        lowered = constraint.lower()
        if any(_first_match(phrases, lowered) is not None for _, phrases in PHRASES.load_phrases):
            _set_load(draft, constraint, f"ограничение производства «{constraint}»")
            return
