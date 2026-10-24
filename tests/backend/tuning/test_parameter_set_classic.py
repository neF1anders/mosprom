from stage1_factory import handoff, report, requirement

from tuning.catalog import read_materials
from tuning.contracts import parameter_set_errors
from tuning.hard_rules import hard_rule_violations
from tuning.space import load_profile

GEAR = dict(
    requirements=[
        requirement("tg_min_c", "85–90", "°C"),
        requirement("high_stiffness", "да"),
        requirement("load_bearing", "Циклическая нагрузка"),
    ],
    preferences=["Важна прочность, затем точность"],
)


def check_hard_rules(parameter_set, materials_dir):
    profile = load_profile()
    material = read_materials(materials_dir, profile["filament_mm"])[parameter_set["materials"]["0"]["id"]]
    assert hard_rule_violations(parameter_set, profile, material) == []


def test_card_gives_a_valid_parameter_set_for_the_issued_printer(select, materials_dir):
    code, parameter_set, err = select(handoff(**GEAR))
    assert code == 0, err
    assert parameter_set_errors(parameter_set) == []
    assert (parameter_set["contract"], parameter_set["version"], parameter_set["iteration"]) == (
        "stage2.parameter_set",
        "0.1",
        1,
    )
    assert parameter_set["printer"] == "hte530v5.2.4"
    assert parameter_set["status"] == "proposed"
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert parameter_set["printing_mode"]["source"] == "rule:MODE-DEFAULT-CLASSIC"
    check_hard_rules(parameter_set, materials_dir)


def test_settings_carry_only_what_differs_from_profile_and_material(select):
    code, parameter_set, err = select(handoff(**GEAR))
    assert code == 0, err
    settings = parameter_set["settings"]
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
    for key in ("material_bed_temperature", "cool_fan_speed", "layer_height", "support_enable", "adhesion_type"):
        assert key not in settings
    assert all(setting["source"].startswith("rule:") and setting["why"] for setting in settings.values())


def test_neutral_card_keeps_slicer_defaults(select):
    code, parameter_set, err = select(handoff())
    assert code == 0, err
    assert parameter_set["quality"] == {
        "quality_type": "normal",
        "why": "профиль по умолчанию принтера: Fine, слой 0.1 мм",
        "source": "default",
    }
    # enduse_abs wins the tie. Its file has no part cooling and recommends 50 mm/s against the slicer's 60,
    # so exactly these two differences are sent.
    assert parameter_set["materials"]["0"]["id"] == "enduse_abs"
    settings = parameter_set["settings"]
    assert sorted(settings) == ["cool_fan_enabled_classic", "speed_print"]
    assert settings["cool_fan_enabled_classic"]["value"] is False
    assert (settings["speed_print"]["value"], settings["speed_print"]["source"]) == (50, "rule:SPEED-MATERIAL-MAX")


def test_speed_priority_moves_to_a_coarser_quality_profile(select):
    code, parameter_set, err = select(handoff(preferences=["Нужно быстро"]))
    assert code == 0, err
    assert parameter_set["quality"]["quality_type"] == "fast"
    assert parameter_set["quality"]["source"] == "rule:PRIORITY-SPEED"
    assert "layer_height" not in parameter_set["settings"]


def test_hard_tolerance_keeps_fine_layers_and_slows_down(select):
    payload = handoff(requirements=[requirement("dimensional_tol_mm", "0.1", "мм")], preferences=["быстро"])
    code, parameter_set, err = select(payload)
    assert code == 0, err
    assert parameter_set["quality"]["quality_type"] in ("normal", "fast")
    speed = parameter_set["settings"]["speed_print"]
    assert speed["value"] < 50 and speed["source"] == "rule:TOL-HARD-FINE-LAYER"


def test_material_speed_recommendation_caps_print_speed(select):
    code, parameter_set, err = select(handoff(**material_requirement("Enduse PA6")))
    assert code == 0, err
    assert parameter_set["materials"]["0"]["source"] == "requirement:material"
    assert parameter_set["settings"]["speed_print"]["value"] == 40
    assert parameter_set["settings"]["speed_print"]["source"] == "rule:SPEED-MATERIAL-MAX"


def test_model_is_placed_in_the_usable_area_as_loaded(select):
    code, parameter_set, err = select(handoff(stl_report=report(size=(30.0, 20.0, 10.0))))
    assert code == 0, err
    (model,) = parameter_set["models"]
    assert model["attachment_id"] == "att-1" and model["extruder"] == 0
    assert model["transform"] == {
        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "position": [-9.5, 0.0, 5.0],
        "scale": [1, 1, 1],
    }
    assumption = [a for a in parameter_set["assumptions"] if "assumption:" + a["id"] == model["source"]]
    assert assumption and assumption[0]["text"].startswith("ориентация «как загружено»")


def material_requirement(name):
    return {"requirements": [requirement("material", name)]}
