import math

import pytest

from src.backend.domain.parameters import ParameterSet
from src.backend.tuning.constraints import wall_lines
from src.backend.tuning.printer import load_printer
from tests.backend.tuning.cards import card, report, requirement

pytestmark = pytest.mark.unit
TOLERANCE = 1e-9

GEAR = dict(
    requirements=[
        requirement("tg_min_c", "85–90", "°C"),
        requirement("high_stiffness", "да"),
        requirement("load_bearing", "Циклическая нагрузка"),
    ],
    preferences=["Важна прочность, затем точность"],
)


def hard_rule_violations(parameter_set, catalog):
    """An independent check of the hard rules of the task (4.2) on a finished parameter set."""
    printer = load_printer(catalog)
    mode = printer.modes[parameter_set["printing_mode"]["value"]]
    quality = mode.qualities[parameter_set["quality"]["quality_type"]]
    material = catalog.materials[parameter_set["materials"]["0"]["id"]]
    settings = parameter_set["settings"]

    def value(key):
        return settings[key]["value"] if key in settings else mode.value(key, quality)

    found = []
    layer = value("layer_height")
    if layer > 0.8 * printer.nozzle + TOLERANCE:
        found.append(f"layer {layer} mm exceeds 0.8 * nozzle")
    if wall_lines(value("wall_thickness"), mode.line_width) < 2:
        found.append("fewer than two walls")
    if math.ceil(round(value("top_bottom_thickness") / layer, 4)) < 3:
        found.append("fewer than three top/bottom layers")
    nozzle = settings.get("material_print_temperature", {}).get("value", material.print_temperature)
    if nozzle > max(mode.temperature_max, material.print_temperature) + TOLERANCE:
        found.append("nozzle temperature above the machine limit")
    if abs(nozzle - material.print_temperature) > 10 + TOLERANCE:
        found.append("nozzle temperature outside the material window")
    if not mode.heated_bed and "material_bed_temperature" in settings:
        found.append("bed temperature sent in a mode without a heated bed")
    if abs(material.diameter - printer.filament) > TOLERANCE:
        found.append("material filament does not fit the extruder")
    return found


def test_card_gives_a_valid_parameter_set_for_the_issued_printer(select, catalog):
    parameter_set = select(card(**GEAR))
    contract = ParameterSet.model_validate(parameter_set)
    assert (contract.contract, contract.version, contract.iteration) == (
        "stage2.parameter_set",
        "0.2",
        1,
    )
    assert parameter_set["printer"] == "hte530v5.2.4"
    assert parameter_set["status"] == "proposed"
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert parameter_set["printing_mode"]["source"] == "rule:MODE-DEFAULT-CLASSIC"
    assert hard_rule_violations(parameter_set, catalog) == []


@pytest.mark.parametrize("mode", ["classic", "cylindrical", "cylindrical_full"])
def test_strong_card_respects_the_hard_rules_in_every_mode(select, catalog, mode):
    strong = card(
        requirements=[
            requirement("high_stiffness", "да"),
            requirement("load_bearing", "циклическая нагрузка"),
            requirement("printing_mode", mode),
        ],
        preferences=["прочность"],
    )
    assert hard_rule_violations(select(strong), catalog) == []


def test_settings_carry_only_what_differs_from_profile_and_material(select):
    settings = select(card(**GEAR))["settings"]
    assert settings["wall_thickness"] == {
        "value": 2.4,
        "unit": "mm",
        "why": settings["wall_thickness"]["why"],
        "source": "rule:LOAD-WALLS",
    }
    assert settings["infill_sparse_density"]["value"] == 40
    assert settings["infill_pattern"]["value"] == "gyroid"
    assert settings["material_print_temperature"]["scope"] == "extruder:0"
    # Values the slicer takes from the material file or the profile anyway are not sent.
    for key in (
        "material_bed_temperature",
        "cool_fan_speed",
        "layer_height",
        "support_enable",
        "adhesion_type",
    ):
        assert key not in settings
    assert all(
        setting["source"].startswith("rule:") and setting["why"] for setting in settings.values()
    )


def test_neutral_card_keeps_slicer_defaults(select):
    parameter_set = select(card())
    assert parameter_set["quality"] == {
        "quality_type": "normal",
        "why": "профиль по умолчанию принтера: Fine, слой 0.1 мм",
        "source": "default",
    }
    # enduse_abs wins the tie. Its file has no part cooling and recommends 50 mm/s against the
    # slicer's 60, so exactly these two differences are sent.
    assert parameter_set["materials"]["0"]["id"] == "enduse_abs"
    settings = parameter_set["settings"]
    assert sorted(settings) == ["cool_fan_enabled_classic", "speed_print"]
    assert settings["cool_fan_enabled_classic"]["value"] is False
    assert (settings["speed_print"]["value"], settings["speed_print"]["source"]) == (
        50,
        "rule:SPEED-MATERIAL-MAX",
    )


def test_speed_priority_moves_to_a_coarser_quality_profile(select):
    parameter_set = select(card(preferences=["Нужно быстро"]))
    assert parameter_set["quality"]["quality_type"] == "fast"
    assert parameter_set["quality"]["source"] == "rule:PRIORITY-SPEED"
    assert "layer_height" not in parameter_set["settings"]


def test_hard_tolerance_keeps_fine_layers_and_slows_down(select):
    tolerance = card(
        requirements=[requirement("dimensional_tol_mm", "0.1", "мм")], preferences=["быстро"]
    )
    parameter_set = select(tolerance)
    assert parameter_set["quality"]["quality_type"] in ("normal", "fast")
    speed = parameter_set["settings"]["speed_print"]
    assert speed["value"] < 50 and speed["source"] == "rule:TOL-HARD-FINE-LAYER"


def test_material_speed_recommendation_caps_print_speed(select):
    parameter_set = select(card(requirements=[requirement("material", "Enduse PETG")]))
    assert parameter_set["materials"]["0"]["id"] == "enduse_petg"
    assert parameter_set["materials"]["0"]["source"] == "requirement:material"
    assert parameter_set["settings"]["speed_print"]["value"] == 45
    assert parameter_set["settings"]["speed_print"]["source"] == "rule:SPEED-MATERIAL-MAX"


def test_model_is_placed_in_the_usable_area_as_loaded(select):
    parameter_set = select(card(stl_report=report(size=(30.0, 20.0, 10.0))))
    (model,) = parameter_set["models"]
    assert model["attachment_id"] == "att-1" and model["extruder"] == 0
    assert model["transform"] == {
        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "position": [-9.5, 0.0, 5.0],
        "scale": [1, 1, 1],
    }
    assumption = [
        a for a in parameter_set["assumptions"] if f"assumption:{a['id']}" == model["source"]
    ]
    assert assumption and assumption[0]["text"].startswith("ориентация «как загружено»")


def test_a_batch_is_told_to_be_one_model_in_the_project(select):
    parameter_set = select(card(requirements=[requirement("quantity", "15", "шт")]))
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert "партия 15 шт.: в проекте одна модель, копии в раскладку не добавлены" in texts
