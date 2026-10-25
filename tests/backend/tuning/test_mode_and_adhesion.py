"""5D from the part class and its axis, the pose the part prints in, and adhesion by mode."""

import pytest

from src.backend.tuning.select import select_parameters
from src.backend.validation.checks import check_parameters
from tests.backend.tuning.cards import card, report, requirement

pytestmark = pytest.mark.unit
# The axis lies along Y in the file; o2 stands it upright, as the STL report measures.
UPRIGHT = [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]


def axial(length=25.0, diameter=60.0, round_part=True, overhang=0.12, upright_overhang=0.004):
    """A part with its axis along Y: as loaded it lies on its side."""
    stl_report = report(size=(diameter, length, diameter), overhang_fraction=overhang, bore=16.0)
    stl_report["revolution"].update(
        is_revolution=round_part,
        axis_direction=[0.0, 1.0, 0.0],
        symmetry_score=1.0,
        outer_diameter_mm=diameter,
        length_along_axis_mm=length,
    )
    stl_report["orientations"] = [
        {
            "id": "o1",
            "source": "as_loaded",
            "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "overhang_area_fraction": overhang,
            "overhang_area_mm2": 300.0,
            "bed_contact_area_mm2": 20.0,
            "extents_mm": [diameter, length, diameter],
        },
        {
            "id": "o2",
            "source": "revolution_axis",
            "rotation": UPRIGHT,
            "overhang_area_fraction": upright_overhang,
            "overhang_area_mm2": 10.0,
            "bed_contact_area_mm2": 900.0,
            "extents_mm": [diameter, diameter, length],
        },
    ]
    return stl_report


def coded(stl_report, *requirements):
    return card(stl_report=stl_report, requirements=list(requirements))


@pytest.mark.parametrize("part_class", ["shaft", "wheel_roller", "bushing_sleeve"])
def test_part_turning_on_a_shaft_prints_in_5d(select, part_class):
    parameter_set = select(coded(axial(), requirement("part_class", part_class)))
    assert parameter_set["printing_mode"] == {
        "value": "cylindrical_full",
        "why": parameter_set["printing_mode"]["why"],
        "source": "rule:MODE-REVOLUTION-5D",
    }


def test_5d_part_stands_on_its_axis_and_supports_follow_that_pose(select):
    parameter_set = select(coded(axial(), requirement("part_class", "wheel_roller")))
    (model,) = parameter_set["models"]
    assert model["orientation_candidate"] == "o2"
    assert model["transform"]["rotation"] == UPRIGHT
    # Centred on the axis of rotation, half the upright height above the table.
    assert model["transform"]["position"] == [0.0, 0.0, 12.5]
    # As loaded 12 % overhangs, upright 0.4 %: no supports.
    assert "support_enable" not in parameter_set["settings"]
    assert parameter_set["settings"]["cylindrical_mode_base_diameter"]["value"] == 16.0


def test_flexible_wheel_stays_in_3d(select):
    flexible = coded(
        axial(), requirement("part_class", "wheel_roller"), requirement("flexible", "да")
    )
    assert select(flexible)["printing_mode"]["value"] == "classic"


@pytest.mark.parametrize(
    ("length", "diameter", "round_part", "mode"),
    [
        # A pump impeller: its blades break the round sections, the part is tall enough.
        (50.7, 134.6, False, "cylindrical_full"),
        # A motor fan: a flat disc.
        (22.0, 169.0, True, "classic"),
    ],
)
def test_impeller_goes_to_5d_unless_it_is_a_flat_disc(select, length, diameter, round_part, mode):
    impeller = coded(axial(length, diameter, round_part), requirement("part_class", "impeller_fan"))
    assert select(impeller)["printing_mode"]["value"] == mode


def test_flat_fan_with_a_round_working_surface_stays_in_3d(select):
    """Stage one may mark the fan's hub as a working surface of revolution; the flat disc
    still prints in 3D, as the organisers label it: an impeller is the impeller rule's."""
    fan = coded(
        axial(22.0, 169.0, True),
        requirement("part_class", "impeller_fan"),
        requirement("functional_surface_of_revolution", "да"),
    )
    assert select(fan)["printing_mode"]["value"] == "classic"


def test_gear_with_a_round_working_surface_stays_in_3d(select):
    gear = coded(
        axial(10.0, 33.0),
        requirement("part_class", "gear"),
        requirement("functional_surface_of_revolution", "да"),
    )
    assert select(gear)["printing_mode"]["value"] == "classic"


def test_round_working_surface_of_a_body_of_revolution_prints_in_5d(select):
    roller = coded(axial(), requirement("functional_surface_of_revolution", "да"))
    assert select(roller)["printing_mode"]["source"] == "rule:MODE-SURFACE-5D"


def test_5d_by_part_class_passes_the_check(catalog, keys):
    shaft = coded(axial(), requirement("part_class", "shaft"))
    assert check_parameters(select_parameters(shaft, catalog, keys), catalog) == []


def test_3d_print_uses_a_skirt(select):
    pla = card(requirements=[requirement("material", "PLA")])
    adhesion = select(pla)["settings"]["adhesion_type"]
    assert (adhesion["value"], adhesion["source"]) == ("skirt", "rule:ADHESION-CLASSIC-SKIRT")


def test_warping_material_gets_a_brim(select):
    # Brim is also the slicer's own value in 3D, so nothing is sent.
    abs_part = card(requirements=[requirement("material", "Enduse ABS")])
    assert "adhesion_type" not in select(abs_part)["settings"]


def test_tall_narrow_part_gets_a_brim(select):
    tall = card(
        stl_report=report(size=(10.0, 12.0, 60.0)),
        requirements=[requirement("material", "PLA")],
    )
    assert "adhesion_type" not in select(tall)["settings"]


def test_5d_spiral_prints_without_adhesion(select):
    spiral = card(requirements=[requirement("printing_mode", "cylindrical")])
    adhesion = select(spiral)["settings"]["adhesion_type"]
    assert (adhesion["value"], adhesion["source"]) == ("none", "rule:ADHESION-SPIRAL-NONE")


def test_5d_keeps_the_raft_of_the_build(select):
    full = card(requirements=[requirement("printing_mode", "cylindrical_full")])
    assert "adhesion_type" not in select(full)["settings"]


def test_symmetric_part_lying_on_its_side_stands_on_its_end_face_in_3d(select):
    gear = select(coded(axial(10.0, 33.0), requirement("part_class", "gear")))
    (model,) = gear["models"]
    assert gear["printing_mode"]["value"] == "classic"
    assert model["orientation_candidate"] == "o2" and model["transform"]["rotation"] == UPRIGHT
    assert "support_enable" not in gear["settings"]


def test_part_without_symmetry_stays_as_loaded_in_3d(select):
    figurine = axial()
    figurine["revolution"].update(is_revolution=False, symmetry_score=0.7)
    (model,) = select(coded(figurine))["models"]
    assert model["orientation_candidate"] == "o1"
    assert model["transform"]["rotation"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_5d_prints_without_supports_whatever_the_flat_overhangs(select):
    overhanging = axial(upright_overhang=0.3)
    parameter_set = select(coded(overhanging, requirement("part_class", "shaft")))
    assert parameter_set["printing_mode"]["value"] == "cylindrical_full"
    assert "support_enable" not in parameter_set["settings"]


def test_a_mode_invented_from_the_production_method_does_not_override_the_part_class(select):
    invented = requirement("printing_mode", "classic", provenance="document")
    invented["sources"] = [
        {"source_id": "s1", "quote": "Метод производства: Аддитивное производство (FDM / FFF)"}
    ]
    wheel = select(coded(axial(50.7, 134.6, False), requirement("part_class", "impeller_fan"), invented))
    assert wheel["printing_mode"]["value"] == "cylindrical_full"
