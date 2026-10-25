import math

import pytest

from src.backend.domain.parameters import ParameterSet
from src.backend.tuning.constraints import wall_lines
from src.backend.tuning.printer import load_printer
from tests.backend.tuning.cards import card, constraint, feedback, report, requirement

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
    layer = settings["layer_height"]
    assert (layer["value"], layer["source"]) == (0.2, "rule:LAYER-STANDARD")
    for key in (
        "material_bed_temperature",
        "cool_fan_speed",
        "support_enable",
    ):
        assert key not in settings
    # The glass-filled ABS of a stiff gear barely warps: a skirt in place of the build's brim.
    assert settings["adhesion_type"]["source"] == "rule:ADHESION-CLASSIC-SKIRT"
    assert all(
        setting["source"].startswith("rule:") and setting["why"] for setting in settings.values()
    )


def test_neutral_card_keeps_slicer_defaults_with_the_standard_layer(select):
    parameter_set = select(card())
    assert parameter_set["quality"] == {
        "quality_type": "normal",
        "why": "профиль принтера по умолчанию: Fine, слой 0.2 мм задан отдельно: обычный слой "
        "0,2 мм, как в типовых проектах Stereotech",
        "source": "default",
    }
    # Nothing tells the materials apart: the slicer's own PLA, not the first id (enduse_abs).
    material = parameter_set["materials"]["0"]
    assert material["id"] == "generic_pla_175"
    assert material["why"].startswith("требования задания не различают")
    # PLA is cooled and has no speed of its own: only the layer, three walls and the skirt of
    # 3D are sent.
    settings = parameter_set["settings"]
    assert sorted(settings) == ["adhesion_type", "layer_height", "wall_thickness"]
    walls = settings["wall_thickness"]
    assert (walls["value"], walls["source"]) == (1.2, "rule:WALLS-STANDARD")


def test_speed_priority_prints_thick_layers_on_the_default_profile(select):
    parameter_set = select(card(preferences=["Нужно быстро"]))
    assert parameter_set["quality"]["quality_type"] == "normal"
    settings = parameter_set["settings"]
    layer = settings["layer_height"]
    assert (layer["value"], layer["source"]) == (0.3, "rule:PRIORITY-SPEED-LAYER")
    # The profile no longer brings the 10 % infill of `fast` with it.
    assert settings["infill_sparse_density"]["value"] == 15


@pytest.mark.parametrize(
    ("level", "layer", "source"),
    [
        ("draft", 0.3, "rule:QUALITY-DRAFT"),
        ("standard", 0.2, "rule:LAYER-STANDARD"),
        ("fine", None, None),
    ],
)
def test_quality_level_code_sets_the_layer(select, level, layer, source):
    settings = select(card(requirements=[requirement("print_quality", level)]))["settings"]
    if layer is None:
        # Fine is the 0.1 mm layer of the default profile itself.
        assert "layer_height" not in settings
        return
    assert (settings["layer_height"]["value"], settings["layer_height"]["source"]) == (
        layer,
        source,
    )


def test_quality_level_wins_over_the_speed_of_the_wishes(select):
    standard = card(requirements=[requirement("print_quality", "standard")], preferences=["быстро"])
    settings = select(standard)["settings"]
    assert settings["layer_height"]["value"] == 0.2
    assert settings["infill_sparse_density"]["value"] == 15


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


def test_layer_between_profile_layers_is_sent_as_is(select):
    narrow = feedback(
        constraint("C1", "layer_height", "min", 0.12),
        constraint("C2", "layer_height", "max", 0.13),
    )
    parameter_set = select(card(), narrow)
    layer = parameter_set["settings"]["layer_height"]
    assert 0.12 <= layer["value"] <= 0.13 and layer["unit"] == "mm"
    assert layer["source"].startswith("constraint:")
    assert parameter_set["quality"]["quality_type"] == "normal"


def test_coarse_profile_keeps_three_skin_layers(select):
    coarse = select(card(), feedback(constraint("C1", "quality_type", "eq", "verydraft")))
    skin = coarse["settings"]["top_bottom_thickness"]
    # 0.3 mm layers: the 0.8 mm default holds only two, three need 0.9 mm.
    assert (skin["value"], skin["source"]) == (0.9, "rule:SKIN-MIN-3-LAYERS")


def test_banned_default_profile_gives_the_nearest_one(select):
    quality = select(card(), feedback(constraint("C1", "quality_type", "ne", "normal")))["quality"]
    # The 0.2 mm standard layer is the layer of `draft` itself, so no layer is sent.
    assert quality["quality_type"] == "draft"
    assert quality["why"].startswith("профиль Fine исключён этапом 3, ближайший — Draft")


def test_requirements_that_tell_materials_apart_win_over_the_slicer_default(select):
    hot = card(requirements=[requirement("service_temp_max_c", "100", "°C")])
    material = select(hot)["materials"]["0"]
    assert material["id"] != "generic_pla_175"
    assert material["why"].startswith("лучший из")


def test_large_part_without_strength_demands_gets_sparse_infill(select):
    large = card(
        stl_report=report(size=(184.0, 218.0, 294.0)),
        requirements=[requirement("material", "PLA")],
    )
    infill = select(large)["settings"]["infill_sparse_density"]
    assert (infill["value"], infill["source"]) == (10, "rule:LARGE-PART-INFILL")


def test_large_part_keeps_the_datasheet_infill_of_its_material(select):
    large = card(
        stl_report=report(size=(184.0, 218.0, 294.0)),
        requirements=[requirement("material", "Enduse PA6")],
    )
    parameter_set = select(large)
    infill = parameter_set["settings"]["infill_sparse_density"]
    assert parameter_set["status"] == "proposed"
    assert (infill["value"], infill["source"]) == (30, "rule:MATERIAL-INFILL-MIN")


def test_decorative_part_needs_no_datasheet_infill(select):
    figurine = card(
        requirements=[
            requirement("material", "Fiberpart PA12 G12"),
            requirement("part_class", "decorative"),
        ]
    )
    assert "infill_sparse_density" not in select(figurine)["settings"]


def test_fine_quality_carries_the_top_skin_with_denser_infill(select):
    fine = card(requirements=[requirement("print_quality", "fine")])
    infill = select(fine)["settings"]["infill_sparse_density"]
    assert (infill["value"], infill["source"]) == (35, "rule:QUALITY-FINE")


def test_quality_level_wins_over_the_accuracy_priority_for_the_layer(select):
    standard = card(
        requirements=[
            requirement("print_quality", "standard"),
            requirement("priority", "accuracy"),
        ]
    )
    settings = select(standard)["settings"]
    assert settings["layer_height"]["value"] == 0.2
    assert settings["speed_print"]["source"] == "rule:PRIORITY-ACCURACY"


@pytest.mark.parametrize(
    ("named", "material"),
    [
        ("зелёный PLA", "generic_pla_175"),
        ("PLA с добавлением поликарбоната", "generic_pla_175"),
        ("пластик Enduse PETG", "enduse_petg"),
    ],
)
def test_material_named_within_a_phrase_is_found_and_told(select, named, material):
    # Validation 051 and 055: «green PLA» was not found and a strong part got ABS.
    strong = card(
        requirements=[
            requirement("material", named),
            requirement("service_temp_max_c", "100", "°C", mandatory=False),
        ]
    )
    parameter_set = select(strong)
    assert parameter_set["materials"]["0"]["id"] == material
    assert parameter_set["materials"]["0"]["source"] == "requirement:material"
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert any(text.startswith(f"материал «{named}» понят как") for text in texts)


def test_material_name_without_a_catalog_word_falls_back_to_the_ranking(select):
    own = card(requirements=[requirement("material", "свой фирменный пластик")])
    parameter_set = select(own)
    assert parameter_set["materials"]["0"]["source"] == "rule:MATERIAL-RANK"
    assert (
        "material 'свой фирменный пластик' from the card is not in the catalog, ranking instead"
        in parameter_set["warnings"]
    )


def test_accuracy_priority_slows_the_print_but_keeps_the_standard_layer(select):
    # Calibration plates of the validation run: the human printed 0.2 mm in 11 of 14.
    accurate = card(requirements=[requirement("priority", "accuracy")])
    settings = select(accurate)["settings"]
    assert (settings["layer_height"]["value"], settings["layer_height"]["source"]) == (
        0.2,
        "rule:LAYER-STANDARD",
    )
    assert settings["speed_print"]["source"] == "rule:PRIORITY-ACCURACY"
