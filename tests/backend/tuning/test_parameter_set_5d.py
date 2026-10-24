import pytest

from tests.backend.tuning.cards import card, report, requirement

pytestmark = pytest.mark.unit


def five_d(mode, **fields):
    return card(requirements=[requirement("printing_mode", mode)], **fields)


def test_5d_mode_requested_by_the_card_is_used_with_its_own_keys(select):
    parameter_set = select(five_d("cylindrical_full"))
    mode = parameter_set["printing_mode"]
    assert mode == {
        "value": "cylindrical_full",
        "why": mode["why"],
        "source": "requirement:printing_mode",
    }
    settings = parameter_set["settings"]
    # No heated bed in 5D; the fan switch of the 5D part has its own key; raft is already the
    # 5D default.
    assert "material_bed_temperature" not in settings
    assert "cool_fan_enabled_cylindrical" in settings and "cool_fan_enabled_classic" not in settings
    assert "adhesion_type" not in settings
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert any(
        text.startswith("диаметр основания 5D оставлен по умолчанию (6 мм)") for text in texts
    )


def test_5d_model_sits_on_the_rotation_axis(select):
    parameter_set = select(five_d("cylindrical", stl_report=report(size=(40.0, 40.0, 20.0))))
    assert parameter_set["models"][0]["transform"]["position"] == [0.0, 0.0, 10.0]


def test_part_taller_than_the_5d_area_stays_classic_and_says_why(select):
    parameter_set = select(five_d("cylindrical", stl_report=report(size=(20.0, 20.0, 250.0))))
    assert parameter_set["printing_mode"]["value"] == "classic"
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert (
        "режим cylindrical не выбран: деталь не помещается в область печати этого режима" in texts
    )
    assert not any(text.startswith("диаметр основания 5D") for text in texts)


def test_part_too_wide_for_3d_is_infeasible_and_names_the_modes_it_would_fit(select):
    # 340 mm: wider than the usable 320 mm of the 3D table, inside the 351 x 300.3 ellipse of 5D.
    parameter_set = select(card(stl_report=report(size=(340.0, 20.0, 20.0))))
    assert parameter_set["status"] == "infeasible"
    (item,) = parameter_set["unsatisfied"]
    assert item["requirement_id"] == "GEOMETRY"
    assert item["why"].endswith("помещаются в: cylindrical, cylindrical_full")


def test_canonical_printing_mode_code_is_read_case_insensitively(select):
    assert select(five_d(" Cylindrical "))["printing_mode"]["value"] == "cylindrical"


def test_unknown_printing_mode_is_a_warning_and_3d_stays(select):
    parameter_set = select(five_d("5d"))
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert (
        "printing mode printing_mode is not one of classic, cylindrical, cylindrical_full"
        in parameter_set["warnings"]
    )
