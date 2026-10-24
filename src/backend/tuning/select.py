"""Stage two: a ready task card (and, on the second pass, the check's feedback) -> the print
parameters as ``stage2.parameter_set`` 0.2.

The decisions follow one chain: material, printing mode, the plan of the rules and the check's
constraints, quality profile, settings, model placement. Nothing is kept between calls: the same
card and feedback always give the same parameter set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..domain.catalog import Catalog
from ..domain.errors import AppError
from ..domain.models import TaskCard
from ..domain.parameters import MAX_ITERATIONS, Constraint, Feedback, ParameterSet
from ..domain.requirement_keys import RequirementKeys
from .axes import LAYER_AXIS, SPACE, AxisContext, build_axes
from .constraints import (
    MATERIAL_KEY,
    MODE_KEY,
    QUALITY_KEY,
    apply_constraints,
    choices_from,
    is_choice,
)
from .facts import build_facts
from .intake import CardRequirement, read_card
from .material_choice import choose_material
from .materials import Candidate, printable_materials
from .mode import choose_mode
from .notes import ConstraintResult, Unmet
from .output import Selection, render
from .placement import place_model
from .planning import build_plan, find_conflicts, plan_unmet
from .printer import Mode, load_printer
from .quality import choose_quality
from .rules import RULE_BY_ID, fired_rules
from .settings import choose_settings


def select_parameters(
    card: TaskCard,
    catalog: Catalog,
    keys: RequirementKeys,
    feedback: Feedback | None = None,
) -> ParameterSet:
    """First pass without feedback; the second and last pass with the feedback on the first."""
    iteration = _iteration(feedback)
    request = read_card(card, keys)
    printer = load_printer(catalog)
    constraints = feedback.constraints if feedback is not None else []
    choices = choices_from(constraints)
    material_choice = choose_material(
        request, printable_materials(catalog, printer.filament), choices
    )
    facts = build_facts(request, material_choice.material)
    fired = fired_rules(facts)
    mode_choice = choose_mode(
        fired, facts, choices, request.mode, request.geometry.size, printer.modes
    )
    mode = printer.modes[mode_choice.value]
    context = _context(mode, printer.nozzle, material_choice.material)
    axes = build_axes(context)
    constrained = apply_constraints(
        build_plan(fired, axes, context),
        [constraint for constraint in constraints if not is_choice(constraint)],
        axes,
        SPACE,
        mode.line_width,
    )
    plan = constrained.plan
    quality = choose_quality(plan, axes[LAYER_AXIS], mode, choices, printer.default_quality)
    settings = choose_settings(
        plan, axes, mode, quality, material_choice.material, constrained.pass_through
    )
    placement = place_model(request, mode, _excluded_orientations(feedback))
    choice_results, choice_unmet = _choice_results(
        constraints,
        {
            MODE_KEY: mode.name,
            QUALITY_KEY: quality.profile.name,
            MATERIAL_KEY: material_choice.material.id,
        },
    )
    conflicts = find_conflicts(plan)
    requirement_ids = _requirement_ids(request.requirements)
    return render(
        Selection(
            job_id=request.job_id,
            revision=request.revision,
            iteration=iteration,
            printer=printer.id,
            mode=mode_choice,
            quality=quality,
            material=material_choice,
            # A value the check demands stays over the one taken from the bore.
            settings={**placement.settings, **settings.settings},
            placement=placement,
            card_assumptions=request.assumptions,
            assumptions=[
                *material_choice.assumptions,
                *mode_choice.assumptions,
                *placement.assumptions,
            ],
            unmet=[
                *material_choice.unmet,
                *constrained.unmet,
                *plan_unmet(plan, conflicts, requirement_ids, RULE_BY_ID),
                *mode_choice.unmet,
                *settings.unmet,
                *placement.unmet,
                *choice_unmet,
            ],
            warnings=[*request.warnings, *material_choice.warnings, *mode_choice.warnings],
            constraint_results=None
            if feedback is None
            else [*choice_results, *constrained.results],
            infeasible=material_choice.infeasible or bool(conflicts) or mode_choice.misfit,
        )
    )


def _iteration(feedback: Feedback | None) -> int:
    """Only the first proposal can be revised, once."""
    if feedback is None:
        return 1
    if feedback.iteration != MAX_ITERATIONS - 1:
        raise AppError(
            f"Обратная связь относится к заходу {feedback.iteration}, "
            f"пересмотреть можно только заход {MAX_ITERATIONS - 1}",
            "feedback_iteration",
        )
    return MAX_ITERATIONS


def _context(mode: Mode, nozzle: float, material: Candidate) -> AxisContext:
    """The machine ceiling never forces a material below the temperature its own file asks for."""
    default_speed = float(mode.value("speed_print"))
    return AxisContext(
        nozzle=nozzle,
        default_speed=default_speed,
        material_temperature=material.print_temperature,
        material_speed=material.speed,
        speed_floor=0.5 * min(material.speed or default_speed, default_speed),
        temperature_max=max(mode.temperature_max, material.print_temperature),
    )


def _excluded_orientations(feedback: Feedback | None) -> list[str | None]:
    if feedback is None:
        return []
    return [
        exclusion.candidate for exclusion in feedback.exclude if exclusion.type == "orientation"
    ]


def _requirement_ids(requirements: Sequence[CardRequirement]) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {}
    for requirement in requirements:
        ids.setdefault(requirement.key, []).append(requirement.id)
    return ids


def _choice_results(
    constraints: Sequence[Constraint], chosen: Mapping[str, str]
) -> tuple[list[ConstraintResult], list[Unmet]]:
    """Choice constraints checked against the final choice: a mode the part does not fit is
    reported, not claimed."""
    results, unmet = [], []
    for constraint in (constraint for constraint in constraints if is_choice(constraint)):
        note = _choice_note(constraint, chosen[constraint.key])
        if note is None:
            why = constraint.reason or constraint.key
            results.append(ConstraintResult(constraint.id, "applied", why))
            continue
        results.append(ConstraintResult(constraint.id, "not_applied", note))
        unmet.append(Unmet(f"constraint:{constraint.id}", note))
    return results, unmet


def _choice_note(constraint: Constraint, chosen: str) -> str | None:
    op, value, key = constraint.op, constraint.value, constraint.key
    if op not in ("eq", "ne", "in"):
        return f"op {op} does not apply to {key}"
    if (op == "eq" and chosen != value) or (op == "ne" and chosen == value):
        return f"{key} {op} cannot be met: {chosen} is chosen"
    if op == "in" and chosen not in value:
        return f"{key} in {value} cannot be met: {chosen} is chosen"
    return None
