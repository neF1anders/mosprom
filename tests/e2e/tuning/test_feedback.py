import pytest
from stage1_factory import constraint, feedback, handoff, report, requirement

from tuning.contracts import parameter_set_errors

STRONG = dict(requirements=[requirement("load_bearing", "ударная нагрузка")], preferences=["прочность"])


def applied(parameter_set):
    return {entry["id"]: entry["result"] for entry in parameter_set["applied_constraints"]}


def test_constraints_on_searched_settings_become_hard_limits_on_the_second_iteration(select):
    code, first, err = select(handoff(**STRONG))
    assert code == 0, err
    assert first["settings"]["infill_sparse_density"]["value"] == 30
    review = feedback(
        constraint("C1", "infill_sparse_density", "max", 25), constraint("C2", "wall_line_count", "min", 5)
    )
    code, second, err = select(handoff(**STRONG), review)
    assert code == 0, err
    assert parameter_set_errors(second) == []
    assert second["iteration"] == 2
    density = second["settings"]["infill_sparse_density"]
    assert density["value"] <= 25 and density["source"] == "constraint:C1"
    # At least five walls; the strength rules still add on top of the validator's minimum.
    assert second["settings"]["wall_thickness"]["value"] >= 2.0
    assert applied(second) == {"C1": "applied", "C2": "applied"}


def test_discrete_and_unmodelled_keys_follow_the_constraints(select):
    review = feedback(
        constraint("C1", "infill_pattern", "eq", "cubic"),
        constraint("C2", "retraction_amount", "eq", 5.0),
        constraint("C3", "cool_fan_enabled_classic", "ne", False),
    )
    code, second, err = select(handoff(**STRONG), review)
    assert code == 0, err
    settings = second["settings"]
    assert settings["infill_pattern"] == {
        "value": "cubic",
        "why": settings["infill_pattern"]["why"],
        "source": "constraint:C1",
    }
    assert settings["retraction_amount"]["value"] == 5.0 and settings["retraction_amount"]["source"] == "constraint:C2"
    # The fan stays at the slicer default (on), so the switch is no longer sent.
    assert "cool_fan_enabled_classic" not in settings


def test_constraints_can_choose_mode_quality_and_material(select):
    review = feedback(
        constraint("C1", "printing_mode", "eq", "cylindrical"),
        constraint("C2", "quality_type", "eq", "draft"),
        constraint("C3", "material", "ne", "enduse_abs"),
    )
    code, second, err = select(handoff(), review)
    assert code == 0, err
    assert second["printing_mode"]["source"] == "constraint:C1" and second["printing_mode"]["value"] == "cylindrical"
    assert second["quality"] == {
        "quality_type": "draft",
        "why": "профиль задан ограничением этапа 3",
        "source": "constraint:C2",
    }
    assert second["materials"]["0"]["id"] != "enduse_abs"
    assert applied(second) == {"C1": "applied", "C2": "applied", "C3": "applied"}


def test_constraint_naming_a_catalog_material_selects_it(select):
    code, second, err = select(handoff(), feedback(constraint("C1", "material", "eq", "enduse_pc")))
    assert code == 0, err
    material = second["materials"]["0"]
    assert (material["id"], material["source"]) == ("enduse_pc", "constraint:C1")
    assert material["why"].startswith("материал задан ограничением этапа 3; ")
    assert applied(second) == {"C1": "applied"}


def test_choice_the_part_cannot_take_is_reported_as_not_applied(select):
    review = feedback(
        constraint("C1", "printing_mode", "eq", "cylindrical"), constraint("C2", "material", "eq", "unobtainium")
    )
    code, second, err = select(handoff(stl_report=report(size=(20.0, 20.0, 250.0))), review)
    assert code == 0, err
    assert second["printing_mode"]["value"] == "classic"
    assert applied(second) == {"C1": "not_applied", "C2": "not_applied"}
    assert sorted(item["requirement_id"] for item in second["unsatisfied"]) == ["constraint:C1", "constraint:C2"]


def test_unsupported_constraint_is_reported_not_silently_dropped(select):
    code, second, err = select(handoff(), feedback(constraint("C1", "speed_print", "ne", 60)))
    assert code == 0, err
    assert applied(second) == {"C1": "not_applied"}
    assert [item["requirement_id"] for item in second["unsatisfied"]] == ["constraint:C1"]


def test_excluding_the_only_orientation_is_reported(select):
    review = feedback(exclude=[{"type": "orientation", "candidate": "o1", "reason": "поддержки в G-code"}])
    code, second, err = select(handoff(), review)
    assert code == 0, err
    assert {"requirement_id": "orientation", "why": "единственный кандидат ориентации исключён этапом 3"} in second[
        "unsatisfied"
    ]


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"iteration": 2}, "only iteration 1 can be revised"),
        ({"contract": "verdict/0"}, "stage3.feedback"),
        ({"constraints": [constraint("C 1", "infill_sparse_density", "max", 10)]}, "must be letters"),
        ({"constraints": [constraint("C1", "infill_sparse_density", "approx", 10)]}, "unknown op"),
    ],
)
def test_malformed_or_late_feedback_is_refused(select, fields, message):
    code, _, err = select(handoff(), feedback(**fields))
    assert code == 2 and message in err
