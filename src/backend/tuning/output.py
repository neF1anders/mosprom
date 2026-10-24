"""Render the decisions of stage two as ``stage2.parameter_set`` 0.2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.parameters import Alternative as AlternativeModel
from ..domain.parameters import (
    AppliedConstraint,
    CardRef,
    Material,
    MaterialCheck,
    ParameterSet,
    PlacedModel,
    PrintingMode,
    Quality,
    SelectionAssumption,
    Setting,
    Transform,
    Unsatisfied,
)
from .material_choice import MaterialChoice
from .mode import ModeChoice
from .notes import ConstraintResult, SettingChoice, Unmet
from .placement import ORIENTATION_ASSUMPTION, ORIENTATION_CANDIDATE, Placement
from .quality import QualityChoice

STAGE1_BASIS = "карточка этапа 1"
STAGE2_BASIS = "решение этапа 2"
# Rotation and scale of the model as loaded.
_IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_UNSCALED = [1.0, 1.0, 1.0]


@dataclass(frozen=True)
class Selection:
    """Everything stage two decided for one card revision."""

    job_id: str
    revision: int
    iteration: int
    printer: str
    mode: ModeChoice
    quality: QualityChoice
    material: MaterialChoice
    settings: Mapping[str, SettingChoice]
    placement: Placement
    # Assumptions of the card and its reading, then those of the decisions.
    card_assumptions: Sequence[str]
    assumptions: Sequence[str]
    unmet: Sequence[Unmet]
    warnings: Sequence[str]
    # Only on the second pass.
    constraint_results: Sequence[ConstraintResult] | None
    infeasible: bool


def render(selection: Selection) -> ParameterSet:
    assumptions, ids = _numbered(selection.card_assumptions, selection.assumptions)
    mode, quality, placement = selection.mode, selection.quality, selection.placement
    results = selection.constraint_results
    return ParameterSet(
        card_ref=CardRef(job_id=selection.job_id, revision=selection.revision),
        iteration=selection.iteration,
        printer=selection.printer,
        printing_mode=PrintingMode.model_validate(
            {"value": mode.value, "why": mode.why, "source": mode.source}
        ),
        quality=Quality(quality_type=quality.profile.name, why=quality.why, source=quality.source),
        materials={"0": _material(selection.material)},
        settings={key: _setting(setting) for key, setting in selection.settings.items()},
        models=[
            PlacedModel(
                id="m1",
                attachment_id=placement.attachment_id,
                extruder=0,
                orientation_candidate=ORIENTATION_CANDIDATE,
                transform=Transform(
                    rotation=_IDENTITY, position=list(placement.position), scale=_UNSCALED
                ),
                why=placement.why,
                source=f"assumption:{ids[ORIENTATION_ASSUMPTION]}",
            )
        ],
        assumptions=assumptions,
        status="infeasible" if selection.infeasible else "proposed",
        unsatisfied=[
            Unsatisfied(requirement_id=u.requirement_id, why=u.why, conflicts_with=u.conflicts_with)
            for u in selection.unmet
        ],
        warnings=list(selection.warnings),
        applied_constraints=None
        if results is None
        else [AppliedConstraint(id=r.id, result=r.result, why=r.why) for r in results],
    )


def _numbered(
    from_card: Sequence[str], from_selection: Sequence[str]
) -> tuple[list[SelectionAssumption], dict[str, str]]:
    """Assumptions A1, A2, ... and the id of each text, for ``source: assumption:<id>``."""
    entries: list[SelectionAssumption] = []
    ids: dict[str, str] = {}
    for texts, basis in ((from_card, STAGE1_BASIS), (from_selection, STAGE2_BASIS)):
        for text in texts:
            if text in ids:
                continue
            ids[text] = f"A{len(entries) + 1}"
            entries.append(SelectionAssumption(id=ids[text], text=text, basis=basis))
    return entries, ids


def _material(choice: MaterialChoice) -> Material:
    return Material(
        id=choice.material.id,
        why=choice.why,
        source=choice.source,
        alternatives=[AlternativeModel(id=a.id, why=a.why) for a in choice.alternatives],
        checks=[
            MaterialCheck(
                requirement_id=c.requirement_id,
                key=c.key,
                hard=c.hard,
                status=c.status,
                detail=c.detail,
            )
            for c in choice.checks
        ],
    )


def _setting(setting: SettingChoice) -> Setting:
    return Setting(
        value=setting.value,
        why=setting.why,
        source=setting.source,
        unit=setting.unit,
        scope=setting.scope,
    )
