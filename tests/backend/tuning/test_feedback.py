import pytest
from pydantic import ValidationError

from src.backend.domain.errors import AppError
from src.backend.domain.parameters import Feedback, ParameterSet
from tests.backend.tuning.cards import (
    card,
    constraint,
    feedback,
    feedback_payload,
    report,
    requirement,
)

pytestmark = pytest.mark.unit

STRONG = dict(
    requirements=[requirement("load_bearing", "ударная нагрузка")], preferences=["прочность"]
)


def applied(parameter_set):
    return {entry["id"]: entry["result"] for entry in parameter_set["applied_constraints"]}


def test_constraints_on_searched_settings_become_hard_limits_on_the_second_iteration(select):
    first = select(card(**STRONG))
    assert first["settings"]["infill_sparse_density"]["value"] == 30
    assert "applied_constraints" not in first
    review = feedback(
        constraint("C1", "infill_sparse_density", "max", 25),
        constraint("C2", "wall_line_count", "min", 5),
    )
    second = select(card(**STRONG), review)
    assert ParameterSet.model_validate(second).iteration == 2
    density = second["settings"]["infill_sparse_density"]
    assert density["value"] <= 25 and density["source"] == "constraint:C1"
    # At least five walls; the strength rules still add on top of the check's minimum.
    assert second["settings"]["wall_thickness"]["value"] >= 2.0
    assert applied(second) == {"C1": "applied", "C2": "applied"}


def test_discrete_and_unmodelled_keys_follow_the_constraints(select):
    review = feedback(
        constraint("C1", "infill_pattern", "eq", "cubic"),
        constraint("C2", "retraction_amount", "eq", 5.0),
        constraint("C3", "cool_fan_enabled_classic", "ne", False),
    )
    settings = select(card(**STRONG), review)["settings"]
    assert settings["infill_pattern"] == {
        "value": "cubic",
        "why": settings["infill_pattern"]["why"],
        "source": "constraint:C1",
    }
    assert (settings["retraction_amount"]["value"], settings["retraction_amount"]["source"]) == (
        5.0,
        "constraint:C2",
    )
    # The fan stays at the slicer default (on), so the switch is no longer sent.
    assert "cool_fan_enabled_classic" not in settings


def test_constraints_can_choose_mode_quality_and_material(select):
    review = feedback(
        constraint("C1", "printing_mode", "eq", "cylindrical"),
        constraint("C2", "quality_type", "eq", "draft"),
        constraint("C3", "material", "ne", "generic_pla_175"),
    )
    second = select(card(), review)
    assert (second["printing_mode"]["value"], second["printing_mode"]["source"]) == (
        "cylindrical",
        "constraint:C1",
    )
    assert second["quality"] == {
        "quality_type": "draft",
        "why": "профиль задан ограничением этапа 3",
        "source": "constraint:C2",
    }
    assert second["materials"]["0"]["id"] != "generic_pla_175"
    assert applied(second) == {"C1": "applied", "C2": "applied", "C3": "applied"}


def test_constraint_naming_a_catalog_material_selects_it(select):
    # The original code raised TypeError here: "requirement:" + None.
    second = select(card(), feedback(constraint("C1", "material", "eq", "enduse_pc")))
    material = second["materials"]["0"]
    assert (material["id"], material["source"]) == ("enduse_pc", "constraint:C1")
    assert material["why"].startswith("материал задан ограничением этапа 3; ")
    assert applied(second) == {"C1": "applied"}


def test_choice_the_part_cannot_take_is_reported_as_not_applied(select):
    review = feedback(
        constraint("C1", "printing_mode", "eq", "cylindrical"),
        constraint("C2", "material", "eq", "unobtainium"),
    )
    second = select(card(stl_report=report(size=(20.0, 20.0, 250.0))), review)
    assert second["printing_mode"]["value"] == "classic"
    assert applied(second) == {"C1": "not_applied", "C2": "not_applied"}
    unmet = sorted(item["requirement_id"] for item in second["unsatisfied"])
    assert unmet == ["constraint:C1", "constraint:C2"]


def test_choice_constraints_are_checked_against_the_final_choice(select):
    review = feedback(
        constraint("C1", "quality_type", "min", "draft"),
        constraint("C2", "printing_mode", "in", ["cylindrical", "cylindrical_full"]),
        constraint("C3", "material", "in", ["enduse_petg", "enduse_pp"]),
    )
    second = select(card(stl_report=report(size=(20.0, 20.0, 250.0))), review)
    assert applied(second) == {"C1": "not_applied", "C2": "not_applied", "C3": "applied"}
    notes = {entry["id"]: entry["why"] for entry in second["applied_constraints"]}
    assert notes["C1"] == "op min does not apply to quality_type"
    assert notes["C2"].startswith("printing_mode in ['cylindrical', 'cylindrical_full']")
    assert second["materials"]["0"]["id"] in ("enduse_petg", "enduse_pp")


def test_discrete_constraints_choose_ban_or_cannot_be_met(select):
    review = feedback(
        constraint("C1", "support_enable", "in", [True]),
        constraint("C2", "infill_pattern", "in", ["honeycomb"]),
        constraint("C3", "adhesion_type", "max", "raft"),
        constraint("C4", "retraction_enable", "ne", True),
    )
    second = select(card(), review)
    settings = second["settings"]
    assert (settings["support_enable"]["value"], settings["support_enable"]["source"]) == (
        True,
        "constraint:C1",
    )
    assert (settings["retraction_enable"]["value"], settings["retraction_enable"]["scope"]) == (
        False,
        "extruder:0",
    )
    assert "infill_pattern" not in settings
    assert {
        "requirement_id": "discrete:infill_pattern",
        "why": "все допустимые значения запрещены",
    } in second["unsatisfied"]
    assert applied(second)["C3"] == "not_applied"


def test_wall_thickness_constraint_counts_lines(select):
    second = select(card(), feedback(constraint("C1", "wall_thickness", "min", 2.0)))
    walls = second["settings"]["wall_thickness"]
    assert (walls["value"], walls["source"]) == (2.0, "constraint:C1")


def test_limits_are_kept_on_the_step_grid(select):
    # The nearest step went past the limit (35 for at most 33) and still counted as applied.
    second = select(card(), feedback(constraint("C1", "speed_print", "max", 33)))
    assert second["settings"]["speed_print"]["value"] == 30
    assert applied(second) == {"C1": "applied"}
    abs_part = card(requirements=[requirement("material", "Enduse ABS")])
    hot = select(abs_part, feedback(constraint("C1", "material_print_temperature", "max", 243)))
    assert hot["settings"]["material_print_temperature"]["value"] <= 243


@pytest.mark.parametrize(
    ("fields", "op", "thickness", "meets"),
    [(STRONG, "max", 1.1, float.__le__), ({}, "min", 0.9, float.__ge__)],
)
def test_wall_thickness_limit_counts_whole_lines_toward_the_limit(
    select, fields, op, thickness, meets
):
    # The nearest line count sent 1.2 mm for at most 1.1 and left 0.8 mm for at least 0.9.
    second = select(card(**fields), feedback(constraint("C1", "wall_thickness", op, thickness)))
    walls = second["settings"].get("wall_thickness", {"value": 0.8})
    assert meets(float(walls["value"]), thickness)
    assert applied(second) == {"C1": "applied"}


def test_limit_no_line_count_meets_is_not_applied(select):
    second = select(card(), feedback(constraint("C1", "wall_thickness", "eq", 1.1)))
    assert applied(second) == {"C1": "not_applied"}
    assert "constraint:C1" in [item["requirement_id"] for item in second["unsatisfied"]]


def test_unsupported_constraint_is_reported_not_silently_dropped(select):
    second = select(card(), feedback(constraint("C1", "speed_print", "ne", 60)))
    assert applied(second) == {"C1": "not_applied"}
    assert [item["requirement_id"] for item in second["unsatisfied"]] == ["constraint:C1"]


def test_unmodelled_key_with_no_values_to_choose_from_is_not_applied(select):
    # The original code took value[0] of the empty list and raised IndexError.
    second = select(card(), feedback(constraint("C1", "retraction_amount", "in", [])))
    assert applied(second) == {"C1": "not_applied"}
    assert "retraction_amount" not in second["settings"]


def test_excluding_the_only_orientation_is_reported(select):
    review = feedback(exclude=[{"type": "orientation", "candidate": "o1", "reason": "поддержки"}])
    second = select(card(), review)
    assert {
        "requirement_id": "orientation",
        "why": "кандидат ориентации o1 исключён этапом 3",
    } in second["unsatisfied"]


def test_feedback_on_the_last_iteration_is_refused(select):
    with pytest.raises(AppError) as refused:
        select(card(), feedback(iteration=2))
    assert refused.value.code == "feedback_iteration"


@pytest.mark.parametrize(
    "fields",
    [
        {"contract": "verdict/0"},
        {"version": "0.2"},
        {"constraints": [constraint("C 1", "infill_sparse_density", "max", 10)]},
        {"constraints": [constraint("C1", "infill_sparse_density", "approx", 10)]},
        {"constraints": [constraint("C1", "infill_pattern", "in", "grid")]},
    ],
)
def test_malformed_feedback_is_refused_at_the_boundary(fields):
    with pytest.raises(ValidationError):
        Feedback.model_validate(feedback_payload(**fields))
