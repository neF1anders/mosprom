"""Methods taken over from the other teams of the case: the stiffness class of a material, heat
by Tg or HDT, the media a polymer family resists, glass fillers, the cost priority, the walls a
thin part can hold and the infill of a shaft under torsion."""

import pytest

from tests.backend.tuning.cards import card, report, requirement

pytestmark = pytest.mark.unit


def chosen(parameter_set):
    return parameter_set["materials"]["0"]["id"]


def with_walls(thickness):
    stl_report = report(size=(60.0, 60.0, 30.0))
    stl_report["normal_chords"] = {
        "status": "estimated",
        "minimum_sampled": thickness / 2,
        "distribution": {"median": thickness},
    }
    return stl_report


def test_flexible_part_gets_a_true_elastomer_not_a_hard_tpu(select):
    parameter_set = select(card(requirements=[requirement("flexible", "да")]))
    # Shore 70D TPU and the carbon-filled TPU of gears are semi-rigid, not elastomers.
    assert chosen(parameter_set) not in {"enduse_tpu_d70", "fiberpart_tpu_c5"}
    (check,) = parameter_set["materials"]["0"]["checks"]
    assert (check["status"], check["detail"]) == ("ok", "flexible=True")


def test_heat_asked_as_tg_is_met_by_the_hdt_of_a_semicrystalline_polymer(select):
    # A water-glycol pump at pH 10: PC does not resist alkali, glass-filled PP keeps its shape
    # far above its Tg.
    parameter_set = select(
        card(
            requirements=[
                requirement("tg_min_c", "130", "°C"),
                requirement("chemical_resistance", "alkali"),
                requirement("hydrophobic", "да"),
                requirement("high_stiffness", "да"),
            ]
        )
    )
    assert chosen(parameter_set) == "fiberpart_pp_g30"


def test_sliding_on_a_polymer_counterpart_prefers_an_unfilled_polyamide(select):
    parameter_set = select(
        card(
            requirements=[
                requirement("low_friction", "да"),
                requirement("abrasion_resistant", "да"),
                requirement("chemical_resistance", "alkali"),
            ]
        )
    )
    assert chosen(parameter_set) == "enduse_pa6"


def test_cost_priority_takes_a_commodity_material_for_a_decorative_part(select):
    parameter_set = select(
        card(
            requirements=[
                requirement("priority", "accuracy, cost"),
                requirement("no_visible_layers", "да"),
                requirement("uv_stable", "да"),
            ]
        )
    )
    material = parameter_set["materials"]["0"]
    assert not material["id"].startswith("fiberpart_")
    assert {"key": "cost", "status": "ok"}.items() <= next(
        check for check in material["checks"] if check["key"] == "cost"
    ).items()


STRONG = [
    requirement("priority", "strength"),
    requirement("high_stiffness", "да"),
    requirement("load_bearing", "cyclic"),
]


def walls_of(select, stl_report):
    return select(card(stl_report=stl_report, requirements=STRONG))["settings"]["wall_thickness"]


def test_walls_of_a_thin_blade_are_capped_by_what_fits_from_both_faces(select):
    # Strength first asks for six walls; a 3.4 mm blade holds 5 lines of 0.4 mm.
    walls = walls_of(select, with_walls(3.4))
    assert (walls["value"], walls["source"]) == (2.0, "rule:WALLS-FIT-SECTION")


def test_the_cap_never_goes_below_the_walls_of_a_hard_stiffness(select):
    assert walls_of(select, with_walls(1.0))["value"] == 1.6


def test_thick_part_keeps_the_walls_its_load_asks_for(select):
    assert walls_of(select, with_walls(20.0)) == walls_of(select, report(size=(60.0, 60.0, 30.0)))


def test_shaft_under_torsion_gets_dense_infill(select):
    parameter_set = select(card(requirements=[requirement("part_class", "shaft")]))
    infill = parameter_set["settings"]["infill_sparse_density"]
    assert infill["value"] >= 40
    assert infill["source"] == "rule:SHAFT-TORSION-INFILL"
