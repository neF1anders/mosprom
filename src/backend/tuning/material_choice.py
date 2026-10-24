"""Pick the material: the one the card, an answer or a check constraint names, or the best
catalog candidate by requirements."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ..domain.errors import AppError
from .constraints import MATERIAL_KEY, Choices
from .intake import CardRequirement, MaterialRequest, RequirementValue, TuningInput
from .materials import Candidate, Printable
from .notes import Unmet
from .ranking import Check, Evaluation, evaluate, rank_materials

RANK_RULE_ID = "MATERIAL-RANK"


@dataclass(frozen=True)
class Alternative:
    id: str
    why: str


@dataclass(frozen=True)
class MaterialChoice:
    """The chosen material and everything the user must hear about it."""

    material: Candidate
    source: str
    why: str
    alternatives: tuple[Alternative, ...]
    checks: tuple[Check, ...]
    unmet: tuple[Unmet, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    infeasible: bool


def choose_material(request: TuningInput, printable: Printable, choices: Choices) -> MaterialChoice:
    """A check constraint ``material eq`` overrides the material the card names."""
    forced = choices.forced.get(MATERIAL_KEY)
    named = request.material
    if forced is not None:
        named = MaterialRequest(str(forced.value), f"constraint:{forced.constraint_id}")
    allowed = {
        material_id: material
        for material_id, material in printable.candidates.items()
        if choices.permits(MATERIAL_KEY, material_id)
    }
    warnings = printable.warnings
    found = printable.find(named.name, allowed) if named is not None else None
    if named is not None and found is None:
        warnings.append(
            f"material '{named.name}' from the card is not in the catalog, ranking instead"
        )
    if named is None or found is None:
        return _ranked(allowed, request.requirements, tuple(warnings))
    choice = _named(found, request.requirements, named, tuple(warnings))
    if forced is None or found.id != forced.value:
        return choice
    return replace(choice, why=f"материал задан ограничением этапа 3; {choice.why}")


def _summary(evaluation: Evaluation) -> str:
    parts = []
    for status, label in (
        ("fail", "не выполнено"),
        ("warn", "частично"),
        ("unknown", "нет данных"),
    ):
        items = [
            f"{check.requirement_id} ({check.detail})"
            for check in evaluation.checks
            if check.status == status
        ]
        if items:
            parts.append(f"{label}: {'; '.join(items)}")
    return f"оценка {evaluation.score:.2f}" + ("; " + "; ".join(parts) if parts else "")


def _check_assumptions(evaluation: Evaluation) -> list[str]:
    """Unverified and partly met requirements are told to the user, never shown as confirmed."""
    notes = []
    for check in evaluation.checks:
        if check.status == "unknown":
            notes.append(
                f"требование {check.requirement_id} не проверено по каталогу: {check.detail}"
            )
        if check.status == "warn" and check.hard:
            notes.append(
                f"обязательное требование {check.requirement_id} материал выполняет "
                f"лишь частично: {check.detail}"
            )
    return notes


def _shown(value: RequirementValue) -> str:
    return str(list(value)) if isinstance(value, tuple) else str(value)


def _source_assumptions(requirements: Sequence[CardRequirement]) -> list[str]:
    return [
        f"требование {r.id} = {_shown(r.value)} — допущение, а не подтверждённый факт"
        for r in requirements
        if r.basis == "assumption"
    ]


def _named(
    material: Candidate,
    requirements: Sequence[CardRequirement],
    named: MaterialRequest,
    warnings: tuple[str, ...],
) -> MaterialChoice:
    evaluation = evaluate(material, requirements)
    unmet = tuple(
        Unmet(check.requirement_id, f"материал {material.id} не выполняет: {check.detail}")
        for check in evaluation.checks
        if check.status == "fail"
    )
    return MaterialChoice(
        material=material,
        source=named.source,
        why=f"материал указан в задании ({named.name}); {_summary(evaluation)}",
        alternatives=(),
        checks=evaluation.checks,
        unmet=unmet,
        assumptions=(*_source_assumptions(requirements), *_check_assumptions(evaluation)),
        warnings=warnings,
        infeasible=False,
    )


def _ranked(
    materials: Mapping[str, Candidate],
    requirements: Sequence[CardRequirement],
    warnings: tuple[str, ...],
) -> MaterialChoice:
    ranked = rank_materials(materials, requirements)
    if not ranked:
        raise AppError("В каталоге нет материалов, которыми можно печатать", "catalog_materials")
    best = ranked[0]
    unmet = tuple(_catalog_conflicts(ranked))
    return MaterialChoice(
        material=best.material,
        source=f"rule:{RANK_RULE_ID}",
        why=f"лучший из {len(ranked)} материалов каталога по требованиям задания; {_summary(best)}",
        alternatives=tuple(Alternative(e.material.id, _summary(e)) for e in ranked[1:3]),
        checks=best.checks,
        unmet=unmet,
        assumptions=(*_source_assumptions(requirements), *_check_assumptions(best)),
        warnings=warnings,
        infeasible=bool(unmet),
    )


def _failed_ids(evaluation: Evaluation) -> set[str]:
    return {c.requirement_id for c in evaluation.checks if c.hard and c.status == "fail"}


def _catalog_conflicts(ranked: Sequence[Evaluation]) -> list[Unmet]:
    """Hard requirements no material meets alone, and pairs no single material meets together."""
    failures = [_failed_ids(evaluation) for evaluation in ranked]
    checkable = {c.requirement_id for e in ranked for c in e.checks if c.hard}
    alone = sorted(i for i in checkable if all(i in failed for failed in failures))
    found = [Unmet(i, "ни один материал каталога его не выполняет") for i in alone]
    rest = sorted(checkable - set(alone))
    for first, second in itertools.combinations(rest, 2):
        if all(first in failed or second in failed for failed in failures):
            found.append(
                Unmet(
                    first,
                    "ни один материал каталога не выполняет оба обязательных требования",
                    conflicts_with=second,
                )
            )
    return found
