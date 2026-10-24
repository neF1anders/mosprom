"""Pick the material: the one the card, an answer or a check constraint names, or the best
catalog candidate by requirements."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from ..domain.errors import AppError
from .constraints import MATERIAL_KEY, Choices
from .intake import CardRequirement, MaterialRequest, RequirementValue, TuningInput
from .materials import Candidate, Printable, mentioned
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


def choose_material(
    request: TuningInput, printable: Printable, choices: Choices, preferred: str
) -> MaterialChoice:
    """A check constraint ``material eq`` overrides the material the card names. ``preferred``
    is the base name of the slicer's own material: it wins a tie of the ranking."""
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
    loose = None
    if named is not None and found is None:
        found = loose = mentioned(named.name, allowed)
    if named is not None and found is None:
        warnings.append(
            f"material '{named.name}' from the card is not in the catalog, ranking instead"
        )
    if named is None or found is None:
        return _ranked(allowed, request.requirements, tuple(warnings), preferred)
    choice = _named(found, request.requirements, named, tuple(warnings))
    if loose is not None:
        note = (
            f"материал «{named.name}» понят как {loose.label} ({loose.id}): "
            "в каталоге нет материала с таким названием, взят названный в нём материал каталога"
        )
        choice = replace(choice, assumptions=(note, *choice.assumptions))
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
        f"требование {requirement.id} = {_shown(requirement.value)} — допущение, "
        "а не подтверждённый факт"
        for requirement in requirements
        if requirement.basis == "assumption"
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
    preferred: str,
) -> MaterialChoice:
    ranked = rank_materials(materials, requirements)
    if not ranked:
        raise AppError("В каталоге нет материалов, которыми можно печатать", "catalog_materials")
    best, why = _best(ranked, preferred)
    unmet = tuple(_catalog_conflicts(ranked))
    others = [other for other in ranked if other is not best]
    return MaterialChoice(
        material=best.material,
        source=f"rule:{RANK_RULE_ID}",
        why=f"{why}; {_summary(best)}",
        alternatives=tuple(Alternative(other.material.id, _summary(other)) for other in others[:2]),
        checks=best.checks,
        unmet=unmet,
        assumptions=(*_source_assumptions(requirements), *_check_assumptions(best)),
        warnings=warnings,
        infeasible=bool(unmet),
    )


def _best(ranked: Sequence[Evaluation], preferred: str) -> tuple[Evaluation, str]:
    """The top of the ranking; when the requirements do not tell the top materials apart, the
    slicer's own material among them rather than the first by name."""
    top = ranked[0]
    tied = [
        found
        for found in ranked
        if (found.hard_failures, found.score) == (top.hard_failures, top.score)
    ]
    default = next((found for found in tied if _is_named(found.material.id, preferred)), None)
    if len(tied) > 1 and default is not None:
        why = (
            f"требования задания не различают {len(tied)} материалов каталога: "
            f"взят материал слайсера по умолчанию ({default.material.label})"
        )
        return default, why
    return top, f"лучший из {len(ranked)} материалов каталога по требованиям задания"


def _is_named(material_id: str, base: str) -> bool:
    """``generic_pla_175`` is the 1.75 mm file of the slicer's ``generic_pla``."""
    return material_id == base or material_id.startswith(f"{base}_")


def _failed_ids(evaluation: Evaluation) -> set[str]:
    return {
        check.requirement_id for check in evaluation.checks if check.hard and check.status == "fail"
    }


def _catalog_conflicts(ranked: Sequence[Evaluation]) -> list[Unmet]:
    """Hard requirements no material meets alone, and pairs no single material meets together."""
    failures = [_failed_ids(evaluation) for evaluation in ranked]
    checkable = {check.requirement_id for item in ranked for check in item.checks if check.hard}
    alone = sorted(key for key in checkable if all(key in failed for failed in failures))
    found = [Unmet(key, "ни один материал каталога его не выполняет") for key in alone]
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
