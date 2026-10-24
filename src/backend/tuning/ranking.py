"""Rank catalog materials against the requirements of the task card."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from operator import attrgetter
from typing import Any, Literal

from .intake import CardRequirement
from .materials import TRAITS, Candidate

Status = Literal["ok", "warn", "fail", "unknown"]
# None: the requirement does not apply (a flag that is not asked for).
Verdict = tuple[Status, str] | None
TextFlags = Mapping[str, bool]

_SCORE: dict[Status, float] = {"ok": 1.0, "warn": 0.4, "unknown": 0.3, "fail": 0.0}
_HARD_WEIGHT, _SOFT_WEIGHT = 3.0, 1.0
_POOL_PREFIXES = ("enduse_", "fiberpart_", "sealant_", "generic_")
# Soluble support filament: never the material of the part itself.
_SUPPORT_ONLY_MARKER = "pva"


@dataclass(frozen=True)
class Check:
    requirement_id: str
    key: str
    hard: bool
    status: Status
    detail: str


@dataclass(frozen=True)
class Evaluation:
    material: Candidate
    checks: tuple[Check, ...]
    score: float

    @property
    def hard_failures(self) -> int:
        return sum(1 for check in self.checks if check.hard and check.status == "fail")


def _scale(value: str | None, mapping: Mapping[str, Status]) -> Status:
    return mapping.get(value or "", "unknown")


def _threshold(trait: str) -> Callable[[Candidate, float, TextFlags], Verdict]:
    """Check that a numeric trait reaches the required value."""
    read = attrgetter(trait)

    def check(material: Candidate, required: float, flags: TextFlags) -> Verdict:
        value = read(material.traits)
        if value is None:
            return "unknown", f"no {trait} data (general knowledge table, not verified)"
        return ("ok" if value >= float(required) else "fail"), f"{trait}={value}"

    return check


def _uv(material: Candidate, required: bool, flags: TextFlags) -> Verdict:
    if not required:
        return None
    if flags["uv_bad"]:
        return "fail", "catalog description says it is not weather resistant"
    if flags["uv_good"]:
        return "ok", "catalog description mentions UV resistance"
    level = material.traits.uv
    return _scale(level, {"good": "ok", "fair": "warn", "poor": "fail"}), f"uv={level}"


def _stems_of(item: str) -> list[str]:
    """Stems for a medium given as our code ("alkali") or as a Russian word ("щёлочи")."""
    stems = TRAITS.chemical_stems
    if item in stems:
        return stems[item]
    word = item.lower().replace("ё", "е")
    return next(
        (stems[code] for code in sorted(stems) if any(stem in word for stem in stems[code])), [word]
    )


def _chemicals(material: Candidate, required: Sequence[str], flags: TextFlags) -> Verdict:
    text = material.description.lower().replace("ё", "е")
    matched = [item for item in required if any(stem in text for stem in _stems_of(item))]
    if len(matched) == len(required):
        return "ok", f"catalog description mentions: {', '.join(matched)}"
    if matched:
        return "warn", f"catalog description covers only: {', '.join(matched)}"
    return "unknown", "catalog description does not mention the required media"


def _flexible(material: Candidate, required: bool, flags: TextFlags) -> Verdict:
    if not required:
        return None
    value = material.traits.flexible
    if value is None:
        return "unknown", "no flexibility data"
    return ("ok" if value else "fail"), f"flexible={value}"


def _density(material: Candidate, required: float, flags: TextFlags) -> Verdict:
    if material.density is None:
        return "unknown", "no density in catalog"
    status: Status = "ok" if material.density <= float(required) else "fail"
    return status, f"density={material.density} g/cm3 (catalog)"


def _level(
    trait: str, mapping: Mapping[str, Status]
) -> Callable[[Candidate, bool, TextFlags], Verdict]:
    """Check a flag against a graded trait."""
    read = attrgetter(trait)

    def check(material: Candidate, required: bool, flags: TextFlags) -> Verdict:
        if not required:
            return None
        level = read(material.traits)
        return _scale(level, mapping), f"{trait}={level}"

    return check


def _food(material: Candidate, required: bool, flags: TextFlags) -> Verdict:
    if not required:
        return None
    if flags["food_safe"]:
        return "ok", "catalog description declares food contact"
    return "unknown", "food contact not declared in the catalog"


def _unverifiable(material: Candidate, required: Any, flags: TextFlags) -> Verdict:
    """The catalog has no data for it: told to the user, the same for every material."""
    if required is False:
        return None
    return "unknown", "cannot be checked from the catalog"


# The value each check receives has the kind of its requirement code (number, flag, list).
_CHECKS: dict[str, Callable[[Candidate, Any, TextFlags], Verdict]] = {
    "tg_min_c": _threshold("tg_c"),
    "service_temp_max_c": _threshold("service_max_c"),
    "hydrophobic": _level("hygroscopic", {"low": "ok", "medium": "warn", "high": "fail"}),
    "uv_stable": _uv,
    "chemical_resistance": _chemicals,
    "flexible": _flexible,
    "density_max_g_cm3": _density,
    "low_friction": _level("friction", {"low": "ok", "medium": "warn", "high": "fail"}),
    "high_friction": _level("friction", {"high": "ok", "medium": "warn", "low": "fail"}),
    "abrasion_resistant": _level("abrasion", {"good": "ok", "fair": "warn", "poor": "fail"}),
    "high_stiffness": _level("stiffness", {"high": "ok", "medium": "warn", "low": "fail"}),
    "food_safe": _food,
    "esd": _unverifiable,
    "no_conductive_fillers": _unverifiable,
    "service_temp_peak_c": _unverifiable,
    "heat_deflection_min_c": _unverifiable,
    "tensile_modulus_min_mpa": _unverifiable,
    "tensile_strength_min_mpa": _unverifiable,
    "elongation_min_pct": _unverifiable,
    "water_absorption_max_pct": _unverifiable,
}
CHECKED_CODES = frozenset(_CHECKS)


def _text_flags(material: Candidate) -> dict[str, bool]:
    text = material.description.lower()
    markers = TRAITS.text_flags.model_dump()
    return {name: any(marker in text for marker in found) for name, found in markers.items()}


def evaluate(material: Candidate, requirements: Sequence[CardRequirement]) -> Evaluation:
    """Verdicts on one material per requirement, and a weighted score."""
    flags = _text_flags(material)
    checks = []
    total_weight = earned = 0.0
    for requirement in requirements:
        check = _CHECKS.get(requirement.key)
        verdict = check(material, requirement.value, flags) if check else None
        if verdict is None:
            continue
        status, detail = verdict
        weight = _HARD_WEIGHT if requirement.hard else _SOFT_WEIGHT
        total_weight += weight
        earned += weight * _SCORE[status]
        checks.append(Check(requirement.id, requirement.key, requirement.hard, status, detail))
    score = earned / total_weight if total_weight else 0.5
    return Evaluation(material, tuple(checks), score)


def rank_materials(
    materials: Mapping[str, Candidate], requirements: Sequence[CardRequirement]
) -> list[Evaluation]:
    """The printable pool, best first; ties go by material id for determinism."""
    pool = [
        material
        for material in materials.values()
        if material.id.startswith(_POOL_PREFIXES) and _SUPPORT_ONLY_MARKER not in material.id
    ]
    evaluations = [evaluate(material, requirements) for material in pool]
    return sorted(
        evaluations, key=lambda found: (found.hard_failures, -found.score, found.material.id)
    )
