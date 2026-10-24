import pytest

from src.backend.tuning.select import select_parameters
from src.backend.validation.checks import check_parameters
from tests.backend.tuning.cards import card, constraint, feedback, report, requirement

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


def test_5d_base_diameter_is_the_bore_rounded_down_to_half_a_millimetre(select):
    parameter_set = select(five_d("cylindrical_full", stl_report=report(bore=16.3)))
    assert parameter_set["settings"]["cylindrical_mode_base_diameter"] == {
        "value": 16.0,
        "unit": "mm",
        "why": "диаметр отверстия детали 16.3 мм по отчёту STL с округлением вниз до 0.5 мм",
        "source": "assumption:stl.revolution.bore",
    }
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert not any(text.startswith("диаметр основания 5D") for text in texts)


def test_base_diameter_from_the_bore_passes_the_check(catalog, keys):
    proposed = five_d("cylindrical_full", stl_report=report(bore=16.3))
    assert check_parameters(select_parameters(proposed, catalog, keys), catalog) == []


def test_bore_narrower_than_the_build_allows_keeps_the_default_base(select):
    parameter_set = select(five_d("cylindrical", stl_report=report(bore=3.2)))
    assert "cylindrical_mode_base_diameter" not in parameter_set["settings"]
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert (
        "диаметр основания 5D оставлен по умолчанию (6 мм), отверстие детали 3.2 мм меньше "
        "допустимого минимума 4 мм"
    ) in texts


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("is_revolution", "деталь по отчёту STL не симметрична вокруг оси отверстия"),
        ("through", "отверстие детали 16.3 мм по отчёту STL не сквозное"),
    ],
)
def test_only_a_through_bore_of_a_body_of_revolution_sets_the_base(select, field, reason):
    stl_report = report(bore=16.3)
    revolution = stl_report["revolution"]
    (revolution if field == "is_revolution" else revolution["bore"])[field] = False
    parameter_set = select(five_d("cylindrical", stl_report=stl_report))
    assert "cylindrical_mode_base_diameter" not in parameter_set["settings"]
    texts = [entry["text"] for entry in parameter_set["assumptions"]]
    assert f"диаметр основания 5D оставлен по умолчанию (6 мм), {reason}" in texts


def test_symmetric_part_with_blades_takes_its_bore_as_the_base(select):
    stl_report = report(bore=8.0)
    stl_report["revolution"].update(is_revolution=False, symmetry_score=1.0)
    settings = select(five_d("cylindrical_full", stl_report=stl_report))["settings"]
    assert settings["cylindrical_mode_base_diameter"]["value"] == 8.0


def test_bore_does_not_set_a_base_in_3d(select):
    parameter_set = select(card(stl_report=report(bore=16.3)))
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert "cylindrical_mode_base_diameter" not in parameter_set["settings"]


def test_base_diameter_demanded_by_the_check_stays_over_the_bore(select):
    review = feedback(constraint("C1", "cylindrical_mode_base_diameter", "max", 12))
    parameter_set = select(five_d("cylindrical", stl_report=report(bore=16.3)), review)
    base = parameter_set["settings"]["cylindrical_mode_base_diameter"]
    assert (base["value"], base["source"]) == (12, "constraint:C1")


def test_unknown_printing_mode_is_a_warning_and_3d_stays(select):
    parameter_set = select(five_d("5d"))
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert (
        "printing mode printing_mode is not one of classic, cylindrical, cylindrical_full"
        in parameter_set["warnings"]
    )
