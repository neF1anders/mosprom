from pathlib import Path

import pytest

from src.backend.domain.catalog import PRINTING_MODES, Catalog
from src.backend.domain.formulas import FormulaError, evaluate
from src.backend.domain.units import dimension
from src.backend.infrastructure.catalog import load_catalog, load_requirement_keys

pytestmark = pytest.mark.unit

SETTINGS = {"speed_print": 60, "printing_mode": "classic", "machine_shape": "elliptic"}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("math.ceil(speed_print * 40 / 60)", 40),
        ("300 if resolveOrValue('printing_mode') in ['classic'] else 231.1", 300),
        ("machine_shape == 'rectangular' or speed_print > 50", True),
        ("not speed_print - 60", True),
        ("1 < 2 <= 2 != 3", True),
        ("1 < 2 > 3", False),
        ("'a' not in ['b']", True),
        ("min(3, 5) + max([1, 2]) + abs(-1) + round(2.4)", 8),
        ("extruderValues('speed_print') == [extruderValue(0, 'speed_print')]", True),
        ("math.floor(math.sqrt(10))", 3),
        ("None if False else (1, 2)", [1, 2]),
        ("speed_print ** 2 % 7", 2),
        ("int(2.7) + sum([1, 2]) + float('1.5')", 6.5),
        ("any([0, 1]) and not all([0, 1])", True),
        ("round(math.tan(math.radians(45)) + math.log(1), 6)", 1.0),
        ("defaultExtruderPosition()", "0"),
    ],
)
def test_formulas_evaluate_the_slicer_expression_language(formula, value):
    assert evaluate(formula, SETTINGS.__getitem__) == value


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os').system('true')",
        "speed_print << 2",
        "[1][0]",
        "(lambda: 1)()",
        "math.pi",
        "[x for x in [1]]",
        "speed_print is None",
        "~speed_print",
        "1 +",
    ],
)
def test_formulas_refuse_anything_outside_the_language(formula):
    with pytest.raises(FormulaError):
        evaluate(formula, SETTINGS.__getitem__)


def test_printer_values_follow_the_printing_mode(catalog):
    classic, spiral, full = (catalog.values(mode) for mode in PRINTING_MODES)
    assert [classic.get(k) for k in ("machine_width", "machine_depth", "machine_height")] == [
        351,
        300.3,
        300,
    ]
    assert (classic.get("machine_shape"), classic.get("machine_heated_bed")) == (
        "rectangular",
        True,
    )
    for mode in (spiral, full):
        assert (mode.get("machine_height"), mode.get("machine_shape")) == (231.1, "elliptic")
        assert mode.get("machine_heated_bed") is False
    assert len(classic.get("machine_disallowed_areas")) == 2
    assert full.get("machine_disallowed_areas") == []


def test_catalog_holds_the_build_profiles_and_materials(catalog):
    assert {q: p.name for q, p in catalog.qualities.items()} == {
        "high": "Extra Fine",
        "normal": "Fine",
        "fast": "Normal",
        "draft": "Draft",
        "verydraft": "Extra Fast",
        "coarse": "Coarse",
        "extra coarse": "Extra Coarse",
    }
    assert catalog.qualities["fast"].values["layer_height"] == "0.15"
    assert catalog.filament_diameter("0") == 1.75
    petg = catalog.materials["enduse_petg"]
    assert (petg.brand, petg.diameter, petg.density) == ("Stereotech", 1.75, 1.3)
    assert petg.print_temperature is not None
    assert len(catalog.materials) == 52
    assert sum(m.diameter == 1.75 for m in catalog.materials.values()) == 34
    assert len(catalog.digest) == 64


def test_definition_carries_the_printer_limits_but_not_its_value(catalog):
    height = catalog.definition("machine_height")
    assert height["type"] == "float" and "value" not in height
    assert catalog.definition("unknown_setting") == {}


def test_values_follow_the_stack_of_settings_of_the_slicer():
    """Значения идут по стеку настроек."""
    stacked = Catalog(
        printer="p",
        digest="",
        settings={"a": {"default_value": 1}, "b": {"value": "a * 2", "default_value": 0}},
        printer_overrides={"a": {"default_value": 2}},
        extruder_overrides={"0": {"a": 3}},
        qualities={},
        materials={},
    )
    assert stacked.values("classic").get("b") == 6
    assert stacked.values("classic", {"a": 4}).get("b") == 8


def test_fdmprinter_formulas_are_evaluated(catalog):
    classic = catalog.values("classic")
    assert classic.get("extruders_enabled_count") == 2
    assert classic.get("z_seam_x") == 351 / 2
    chosen = catalog.values("classic", {"top_bottom_thickness": 1.2, "layer_height": 0.2})
    assert (chosen.get("bottom_thickness"), chosen.get("bottom_layers")) == (1.2, 6)


def test_formulas_that_refer_to_each_other_are_an_error():
    looped = Catalog(
        printer="p",
        digest="",
        settings={"a": {"default_value": 1}},
        printer_overrides={"a": {"value": "b + 1"}, "b": {"value": "a + 1"}},
        extruder_overrides={},
        qualities={},
        materials={},
    )
    with pytest.raises(FormulaError):
        looped.values("classic").get("a")


def test_shared_requirement_codes_load_with_units_stage_one_understands():
    codes = load_requirement_keys(Path("knowledge/requirement_keys.json"))
    assert codes.version == "2"
    assert len({entry.key for entry in codes.keys}) == len(codes.keys) == 34
    assert codes.get("service_temp_max_c").unit == "°C"
    assert codes.get("part_class").kind == "choice"
    assert codes.get("priority").options == ["strength", "accuracy", "speed", "cost"]
    assert "Vicat" in codes.get("tg_min_c").hint
    assert codes.get("printing_mode").options == list(PRINTING_MODES)
    assert codes.get("temperature_max") is None
    for entry in codes.keys:
        assert entry.unit is None or dimension(entry.unit) is not None, entry.key


def test_an_extruder_constant_value_wins_over_its_default(catalog):
    """Константа экструдера важнее умолчания."""
    main = catalog.extruder_overrides["0"]
    assert (main["machine_extruder_start_pos_x"], main["machine_extruder_end_pos_x"]) == (15, 0)
