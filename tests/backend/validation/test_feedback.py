import pytest

from src.backend.domain.parameters import Issue
from src.backend.validation.checks import check_parameters
from src.backend.validation.feedback import KINDS, build_feedback, stage_two_errors

from .cases import PORTED, parameter_set

pytestmark = pytest.mark.unit


def feedback_for(name, catalog, iteration=1):
    issues = check_parameters(parameter_set(name), catalog)
    return build_feedback(issues, iteration), issues


@pytest.mark.parametrize(
    ("name", "constraints"),
    [
        ("extra_above_max", [("above_max.cool_fan_speed", "max", 100.0, "error")]),
        (
            "selftest_layer_height_zero",
            [
                ("below_min.layer_height", "min", 0.001, "error"),
                ("below_recommended.layer_height", "min", 0.04, "warning"),
            ],
        ),
        (
            "extra_recommended_bounds",
            [
                ("below_recommended.wall_line_count", "min", 1.0, "warning"),
                ("above_recommended.infill_sparse_density", "max", 100.0, "warning"),
            ],
        ),
        ("selftest_filament_285", [("wrong_filament.material", "ne", "generic_pla", "error")]),
        ("extra_second_extruder_285", [("wrong_filament.material", "ne", "generic_pla", "error")]),
        (
            "selftest_unlinked_mode_key",
            [("unlinked_mode_key.cool_fan_enabled_classic", "eq", False, "warning")],
        ),
    ],
)
def test_limits_materials_and_mode_variants_become_constraints(name, constraints, catalog):
    feedback, issues = feedback_for(name, catalog)
    assert feedback.result == "needs_changes"
    assert [(c.id, c.op, c.value, c.severity) for c in feedback.constraints] == constraints
    assert [c.key for c in feedback.constraints] == [issue.key for issue in issues]
    assert [c.reason for c in feedback.constraints] == [issue.message for issue in issues]
    assert feedback.exclude == [] and feedback.warnings == []


def test_unknown_choices_are_narrowed_to_what_the_build_has(catalog):
    enum, _ = feedback_for("selftest_enum_out_of_list", catalog)
    quality, _ = feedback_for("selftest_unknown_quality", catalog)
    material, _ = feedback_for("extra_unknown_material", catalog)
    fitting = sorted(key for key, profile in catalog.materials.items() if profile.diameter == 1.75)
    assert [(c.id, c.key, c.op, c.value) for c in (*enum.constraints, *quality.constraints)] == [
        (
            "not_in_enum.infill_pattern",
            "infill_pattern",
            "in",
            list(catalog.definition("infill_pattern")["options"]),
        ),
        ("unknown_quality.quality_type", "quality_type", "in", sorted(catalog.qualities)),
    ]
    assert [(c.id, c.key, c.op, c.value) for c in material.constraints] == [
        ("unknown_material.material", "material", "in", fitting)
    ]


@pytest.mark.parametrize(
    "name", ["selftest_not_a_rotation", "extra_rotation_not_3x3", "extra_mirror_rotation"]
)
def test_a_matrix_that_is_no_rotation_drops_its_orientation_candidate(name, catalog):
    feedback, _ = feedback_for(name, catalog)
    assert feedback.result == "needs_changes" and feedback.constraints == []
    assert [(e.type, e.candidate) for e in feedback.exclude] == [("orientation", "o1")]


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("selftest_support_angle_without_supports", "support_angle"),
        ("selftest_bed_temperature_in_5d", "material_bed_temperature"),
        ("selftest_classic_key_in_cylindrical", "cool_fan_enabled_classic"),
        ("extra_cylindrical_key_in_classic", "cool_fan_enabled_cylindrical"),
    ],
)
def test_findings_without_an_operation_are_warnings_only(name, key, catalog):
    feedback, issues = feedback_for(name, catalog)
    assert feedback.result == "ok" and feedback.constraints == [] and feedback.exclude == []
    assert [(w.key, w.reason) for w in feedback.warnings] == [(key, issues[0].message)]


@pytest.mark.parametrize(
    ("name", "kinds"),
    [
        ("selftest_key_typo", ["unknown_key"]),
        ("selftest_int_for_bool", ["wrong_type"]),
        ("extra_wrong_numbers", ["wrong_type", "wrong_type"]),
        ("extra_other_printer", ["wrong_printer"]),
        ("extra_no_materials_no_models", ["no_materials", "no_models"]),
        ("extra_bad_scale", ["bad_scale"]),
        ("extra_position_two_numbers", ["bad_position"]),
        ("selftest_model_outside_bed", ["outside_bed"]),
        ("extra_elliptic_bed_corner", ["outside_bed"]),
        ("extra_height_out_of_range", ["height_out_of_range"]),
        ("extra_below_bed", ["height_out_of_range"]),
    ],
)
def test_stage_two_bugs_stop_the_pipeline_instead_of_feedback(name, kinds, catalog):
    feedback, issues = feedback_for(name, catalog)
    assert [issue.kind for issue in stage_two_errors(issues)] == kinds
    assert (feedback.result, feedback.constraints, feedback.exclude, feedback.warnings) == (
        "ok",
        [],
        [],
        [],
    )


def test_notes_for_people_are_not_passed_on(catalog):
    feedback, issues = feedback_for("extra_condition_outside_the_language", catalog)
    assert [issue.kind for issue in issues] == ["formula_unknown"]
    assert feedback.model_dump() == build_feedback([], 1).model_dump()
    assert stage_two_errors(issues) == []


def test_clean_set_is_ok_on_the_last_pass(catalog):
    feedback, issues = feedback_for("stage2_petg_service_temperature", catalog, iteration=2)
    assert issues == [] and (feedback.iteration, feedback.result) == (2, "ok")


def test_one_constraint_per_id_when_two_extruders_share_a_finding():
    def wrong(position, material):
        return Issue(
            level="error",
            where=f"materials[{position}]",
            kind="wrong_filament",
            message="Пруток материала 2,85 мм, а экструдер под 1,75 мм",
            key="material",
            bound=material,
        )

    feedback = build_feedback([wrong("0", "generic_pla"), wrong("1", "generic_abs")], 1)
    assert [(c.id, c.value) for c in feedback.constraints] == [
        ("wrong_filament.material", "generic_pla")
    ]


def test_a_kind_without_a_rule_fails_loudly():
    issue = Issue(level="error", where="settings.x", kind="new_kind", message="x", key="x")
    with pytest.raises(KeyError):
        build_feedback([issue], 1)


def test_every_kind_of_finding_has_a_rule_and_a_fixture(catalog):
    found = {
        issue.kind for name in PORTED for issue in check_parameters(parameter_set(name), catalog)
    }
    assert found == KINDS
