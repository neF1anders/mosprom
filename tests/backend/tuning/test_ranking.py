import pytest

from src.backend.tuning.intake import CardRequirement
from src.backend.tuning.materials import printable_materials
from src.backend.tuning.ranking import evaluate, rank_materials

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def materials(catalog):
    return printable_materials(catalog, 1.75).candidates


def hard(key, value):
    return CardRequirement(key, key, value, True, "user")


@pytest.mark.parametrize(
    ("material_id", "key", "value", "status", "detail"),
    [
        ("enduse_pa6", "hydrophobic", True, "fail", "hygroscopic=high"),
        ("enduse_pc", "hydrophobic", True, "warn", "hygroscopic=medium"),
        (
            "enduse_abs",
            "uv_stable",
            True,
            "fail",
            "catalog description says it is not weather resistant",
        ),
        ("enduse_petg", "uv_stable", True, "warn", "uv=fair"),
        ("sealant_tpu", "flexible", True, "ok", "flexible=True"),
        ("enduse_pp", "density_max_g_cm3", 1.0, "ok", "density=0.9 g/cm3 (catalog)"),
        ("enduse_pc", "density_max_g_cm3", 1.0, "fail", "density=1.2 g/cm3 (catalog)"),
        ("enduse_pa6", "low_friction", True, "ok", "friction=low"),
        ("generic_pla_175", "abrasion_resistant", True, "fail", "abrasion=poor"),
        ("enduse_pc", "high_stiffness", True, "warn", "stiffness=medium"),
        ("fiberpart_pc_g20", "high_stiffness", True, "ok", "stiffness=high"),
        (
            "enduse_pc",
            "chemical_resistance",
            ["alkali"],
            "fail",
            "the polymer family is known not to resist: alkali",
        ),
        (
            "fiberpart_pp_g30",
            "chemical_resistance",
            ["alkali"],
            "ok",
            "catalog description mentions: alkali",
        ),
        ("fiberpart_pp_g30", "tg_min_c", 130.0, "ok", "tg_c=-10, hdt_c=150"),
        (
            "fiberpart_pa12_g12",
            "low_friction",
            True,
            "warn",
            "friction=low, but the glass filler wears a polymer counterpart",
        ),
        ("enduse_petg", "no_visible_layers", True, "ok", "no fibre filler"),
        (
            "fiberpart_abspa_g8",
            "no_visible_layers",
            True,
            "warn",
            "fibre filler leaves a rough matte surface",
        ),
        ("fiberpart_pp_g30", "heat_deflection_min_c", 130.0, "ok", "hdt_c=150"),
        ("enduse_petg", "food_safe", True, "unknown", "food contact not declared in the catalog"),
        ("enduse_pc", "esd", True, "unknown", "cannot be checked from the catalog"),
        (
            "sealant_tpu",
            "tg_min_c",
            60.0,
            "unknown",
            "no tg_c or hdt_c data (general knowledge table, not verified)",
        ),
        ("enduse_pa6", "service_temp_max_c", 90.0, "ok", "service_max_c=100"),
        (
            "sealant_tpu",
            "chemical_resistance",
            ("кислоты", "озон"),
            "warn",
            "catalog description covers only: кислоты",
        ),
        (
            "enduse_pa6",
            "chemical_resistance",
            ("alkali", "fuel"),
            "ok",
            "catalog description mentions: alkali, fuel",
        ),
        (
            "enduse_petg",
            "chemical_resistance",
            ("озон",),
            "unknown",
            "catalog description does not mention the required media",
        ),
    ],
)
def test_each_requirement_code_is_checked_against_the_catalog_and_traits(
    materials, material_id, key, value, status, detail
):
    (check,) = evaluate(materials[material_id], [hard(key, value)]).checks
    assert (check.status, check.detail) == (status, detail)


def test_a_flag_that_is_not_asked_for_is_not_checked(materials):
    evaluation = evaluate(materials["enduse_pa6"], [hard("hydrophobic", False)])
    assert evaluation.checks == () and evaluation.score == 0.5


def test_ranking_puts_hard_failures_last_and_leaves_out_support_filament(materials):
    ranked = rank_materials(materials, [hard("flexible", True)])
    assert all("pva" not in found.material.id for found in ranked)
    assert {found.material.id for found in ranked} >= {"sealant_tpu", "enduse_abs"}
    failures = [found.hard_failures for found in ranked]
    assert failures == sorted(failures) and failures[0] == 0
