import pytest
from pydantic import ValidationError

from src.backend.domain.parameters import Constraint, Feedback, ParameterSet, Setting
from src.backend.domain.pipeline import FIRST_STEP, Step, next_step
from src.backend.pipeline.parameters import _count

pytestmark = pytest.mark.unit


def parameter_set(**changes) -> dict:
    reason = {"why": "профиль по умолчанию", "source": "default"}
    return {
        "card_ref": {"job_id": "job", "revision": 3},
        "iteration": 1,
        "printer": "hte530v5.2.4",
        "printing_mode": {"value": "classic", **reason},
        "quality": {"quality_type": "normal", **reason},
        "materials": {"0": {"id": "generic_petg_175", **reason}},
        "settings": {"infill_sparse_density": {"value": 30.0, "unit": "%", **reason}},
        "models": [
            {
                "id": "m1",
                "attachment_id": "att",
                "extruder": 0,
                "orientation_candidate": "o1",
                "transform": {
                    "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "position": [-9.5, 0.0, 15.0],
                    "scale": [1, 1, 1],
                },
                **reason,
            }
        ],
        "status": "proposed",
        **changes,
    }


def test_published_parameter_set_leaves_out_unset_optional_fields():
    published = ParameterSet.model_validate(parameter_set()).published()
    assert published["version"] == "0.2" and published["contract"] == "stage2.parameter_set"
    assert "applied_constraints" not in published
    assert "scope" not in published["settings"]["infill_sparse_density"]
    assert published["settings"]["infill_sparse_density"]["value"] == 30.0


@pytest.mark.parametrize(
    "change",
    [
        {"iteration": 3},
        {"version": "0.1"},
        {"idempotency_key": "job:3"},
        {"printing_mode": {"value": "5d", "why": "x", "source": "default"}},
        {"quality": {"quality_type": "normal", "why": " ", "source": "default"}},
        {"quality": {"quality_type": "normal", "why": "x", "source": "rule#1"}},
    ],
)
def test_parameter_set_refuses_what_the_contract_does_not_allow(change):
    with pytest.raises(ValidationError):
        ParameterSet.model_validate(parameter_set(**change))


def test_settings_keep_their_json_type():
    assert Setting(value=True, why="x", source="rule:A").value is True
    assert Setting(value=2, why="x", source="rule:A").value == 2
    assert isinstance(Setting(value=2.0, why="x", source="rule:A").value, float)


def test_feedback_constraints_are_well_formed():
    with pytest.raises(ValidationError):
        Constraint(id="C1", key="infill_pattern", op="in", value="grid")
    with pytest.raises(ValidationError):
        Constraint(id="C 1", key="infill_pattern", op="eq", value="grid")
    duplicate = {"id": "C1", "key": "support_enable", "op": "eq", "value": False}
    with pytest.raises(ValidationError):
        Feedback(iteration=1, result="needs_changes", constraints=[duplicate, duplicate])
    assert Feedback(iteration=1, result="ok").constraints == []


@pytest.mark.parametrize(
    ("step", "check", "after"),
    [
        (FIRST_STEP, None, Step("validation", 1)),
        (FIRST_STEP, "infeasible", None),
        (Step("validation", 1), "ok", Step("slicing", 1)),
        (Step("validation", 1), "needs_changes", Step("parameters", 2)),
        (Step("parameters", 2), None, Step("validation", 2)),
        # последний проход режется
        (Step("validation", 2), "needs_changes", Step("slicing", 2)),
        (Step("validation", 2), "ok", Step("slicing", 2)),
        (Step("slicing", 1), "ok", Step("gcode", 1)),
        (Step("slicing", 1), "failed", None),
        (Step("gcode", 1), "ok", None),
        (Step("gcode", 1), "needs_changes", Step("parameters", 2)),
        (Step("gcode", 2), "needs_changes", None),
    ],
)
def test_selection_is_checked_sliced_and_revised_at_most_once(step, check, after):
    assert next_step(step, check) == after


@pytest.mark.parametrize(
    ("number", "text"),
    [
        (1, "1 настройка"),
        (3, "3 настройки"),
        (5, "5 настроек"),
        (11, "11 настроек"),
        (21, "21 настройка"),
        (0, "0 настроек"),
    ],
)
def test_counts_read_as_russian(number, text):
    assert _count(number, ("настройка", "настройки", "настроек")) == text
