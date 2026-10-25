from typing import get_args

import pytest

from src.backend.domain.catalog import PRINTING_MODES
from src.backend.domain.parameters import ParameterSet, PrintingMode
from src.backend.tuning.printer import load_printer
from src.backend.validation.checks import check_parameters

from .cases import NAMES, load, parameter_set

pytestmark = pytest.mark.unit

# самопроверка оригинала
SELFTEST = {
    "selftest_filament_285": ("error", "wrong_filament", "materials[0]"),
    "selftest_unknown_quality": ("error", "unknown_quality", "quality.quality_type"),
    "selftest_layer_height_zero": ("error", "below_min", "settings.layer_height"),
    "selftest_key_typo": ("error", "unknown_key", "settings.infil_sparse_density"),
    "selftest_enum_out_of_list": ("error", "not_in_enum", "settings.infill_pattern"),
    "selftest_int_for_bool": ("error", "wrong_type", "settings.support_enable"),
    "selftest_support_angle_without_supports": (
        "warning",
        "inactive_in_mode",
        "settings.support_angle",
    ),
    "selftest_bed_temperature_in_5d": (
        "warning",
        "inactive_in_mode",
        "settings.material_bed_temperature",
    ),
    "selftest_unlinked_mode_key": ("warning", "unlinked_mode_key", "settings.cool_fan_enabled"),
    "selftest_classic_key_in_cylindrical": (
        "warning",
        "mode_key_mismatch",
        "settings.cool_fan_enabled_classic",
    ),
    "selftest_not_a_rotation": ("error", "bad_rotation", "models[0]"),
    "selftest_model_outside_bed": ("error", "outside_bed", "models[0]"),
}
CLEAN = ["example_bracket_petg_classic", *(name for name in NAMES if name.startswith("stage2_"))]


@pytest.mark.parametrize("name", SELFTEST)
def test_selftest_case_is_found(name, catalog):
    findings = check_parameters(parameter_set(name), catalog)
    assert SELFTEST[name] in [(issue.level, issue.kind, issue.where) for issue in findings]


@pytest.mark.parametrize("name", CLEAN)
def test_selected_parameters_pass_without_errors_or_warnings(name, catalog):
    assert check_parameters(parameter_set(name), catalog) == []


def test_contract_allows_exactly_the_printing_modes_of_the_build():
    assert get_args(PrintingMode.model_fields["value"].annotation) == PRINTING_MODES


@pytest.mark.parametrize(
    ("name", "kinds"),
    [
        ("extra_classic_key_in_cylindrical_full", []),
        ("extra_cylindrical_key_in_classic", ["mode_key_mismatch"]),
        ("extra_rectangular_bed_corner", []),
        ("extra_elliptic_bed_corner", ["outside_bed"]),
        ("extra_height_out_of_range", ["height_out_of_range"]),
        ("extra_below_bed", ["height_out_of_range"]),
        ("extra_rotation_not_3x3", ["bad_rotation"]),
        ("extra_mirror_rotation", ["bad_rotation"]),
        ("extra_bad_scale", ["bad_scale"]),
        ("extra_position_two_numbers", ["bad_position"]),
        ("extra_second_extruder_285", ["wrong_filament"]),
        ("extra_unknown_material", ["unknown_material"]),
        ("extra_no_materials_no_models", ["no_materials", "no_models"]),
        ("extra_other_printer", ["wrong_printer"]),
        ("extra_wrong_numbers", ["wrong_type", "wrong_type"]),
        ("extra_condition_outside_the_language", ["formula_unknown"]),
        ("extra_recommended_bounds", ["below_recommended", "above_recommended"]),
        ("extra_above_max", ["above_max"]),
    ],
)
def test_each_rule_reports_its_kind(name, kinds, catalog):
    assert [issue.kind for issue in check_parameters(parameter_set(name), catalog)] == kinds


def test_findings_name_the_key_and_the_bound_feedback_needs(catalog):
    layer, recommended = check_parameters(parameter_set("selftest_layer_height_zero"), catalog)
    assert (layer.key, layer.bound, layer.message) == (
        "layer_height",
        0.001,
        "0 меньше минимума 0,001",
    )
    assert (recommended.level, recommended.bound) == ("warning", 0.04)
    (unlinked,) = check_parameters(parameter_set("selftest_unlinked_mode_key"), catalog)
    assert (unlinked.where, unlinked.key, unlinked.bound) == (
        "settings.cool_fan_enabled",
        "cool_fan_enabled_classic",
        False,
    )
    (material,) = check_parameters(parameter_set("extra_unknown_material"), catalog)
    fitting = [key for key, profile in catalog.materials.items() if profile.diameter == 1.75]
    assert (material.key, material.bound) == ("material", sorted(fitting))
    (rotation,) = check_parameters(parameter_set("selftest_not_a_rotation"), catalog)
    assert rotation.bound == "o1"


def test_conditions_follow_fdmprinter_formulas(catalog):
    """Условия следуют формулам fdmprinter."""
    changed = load("extra_fdmprinter_formula_default")["parameter_set"]
    assert check_parameters(ParameterSet.model_validate(changed), catalog) == []
    changed["settings"]["support_enable"]["value"] = False
    (finding,) = check_parameters(ParameterSet.model_validate(changed), catalog)
    assert (finding.kind, finding.where) == (
        "inactive_in_mode",
        "settings.support_offset_cylindrical",
    )


def test_limits_written_as_formulas_are_compared(catalog):
    """Пределы-формулы сравниваются корректно."""
    changed = load("example_bracket_petg_classic")["parameter_set"]
    changed["settings"]["speed_print"] = {"value": 100000, "why": "x", "source": "rule:T"}
    changed["settings"]["top_thickness"] = {"value": 5000, "why": "x", "source": "rule:T"}
    found = check_parameters(ParameterSet.model_validate(changed), catalog)
    feed = catalog.values("classic")
    fastest = (
        feed.get("machine_max_feedrate_x") ** 2 + feed.get("machine_max_feedrate_y") ** 2
    ) ** 0.5
    assert [(issue.level, issue.kind, issue.key, issue.bound) for issue in found] == [
        ("error", "above_max", "speed_print", fastest),
        ("warning", "above_recommended", "speed_print", 150.0),
        ("error", "above_max", "top_thickness", 300),
    ]


def test_formula_limits_see_the_quality_profile_and_the_mode(catalog):
    """Пределы-формулы видят профиль и режим."""
    changed = load("example_bracket_petg_classic")["parameter_set"]
    changed["settings"]["top_thickness"] = {"value": 0.3, "why": "x", "source": "rule:T"}
    (thin,) = check_parameters(ParameterSet.model_validate(changed), catalog)
    assert (thin.kind, thin.bound) == ("below_recommended", 0.4)
    changed["printing_mode"]["value"] = "cylindrical_full"
    changed["settings"]["top_thickness"]["value"] = 250
    kinds = [
        (i.kind, i.bound) for i in check_parameters(ParameterSet.model_validate(changed), catalog)
    ]
    assert ("above_max", 231.1) in kinds


def test_conditions_see_what_parameter_selection_sees(catalog):
    """Условия видны и выбору."""
    classic = load_printer(catalog).modes["classic"]
    assert classic.value("extruders_enabled_count") == 2
    changed = load("example_bracket_petg_classic")["parameter_set"]
    changed["settings"]["prime_tower_enable"] = {"value": True, "why": "x", "source": "rule:T"}
    changed["settings"]["print_sequence"] = {
        "value": "one_at_a_time",
        "why": "x",
        "source": "rule:T",
    }
    found = check_parameters(ParameterSet.model_validate(changed), catalog)
    assert [(issue.kind, issue.key) for issue in found] == [("inactive_in_mode", "print_sequence")]


def test_an_option_that_is_not_a_string_is_reported_not_raised(catalog):
    changed = load("example_bracket_petg_classic")["parameter_set"]
    changed["settings"]["infill_pattern"]["value"] = ["grid"]
    (finding,) = check_parameters(ParameterSet.model_validate(changed), catalog)
    assert finding.kind == "not_in_enum"
