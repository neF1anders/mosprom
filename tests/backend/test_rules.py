"""Acceptance rules: no fabricated dimensions, no approval by silence."""

import pytest

from src.backend.domain.models import Conflict, Geometry, Requirement, TaskCard
from src.backend.domain.rules import assess, comparable, normalize_quantity

pytestmark = pytest.mark.unit


def card(**kwargs):
    return TaskCard(purpose="Шестерня привода", **kwargs)


@pytest.mark.parametrize("units", ["unknown", "", None])
def test_unknown_units_blocks_parameters_not_materials(units):
    result = assess(card(geometry=Geometry(readable=True, units=units or "unknown")))
    assert "assess_materials" in result.allowed_actions
    assert "select_parameters" not in result.allowed_actions
    assert any(q.id == "geometry.units" for q in result.questions)


@pytest.mark.parametrize(
    "defect",
    [
        "boundary_edges",
        "duplicate_faces",
        "nonmanifold_edges",
        "inconsistent_winding",
        "multiple_shells",
    ],
)
def test_defects_do_not_block_independent_work(defect):
    result = assess(card(geometry=Geometry(readable=True, units="mm", defects=[defect])))
    assert "assess_materials" in result.allowed_actions
    assert not result.geometry.physical_volume_confirmed


@pytest.mark.parametrize("answer", [None, "", "Не знаю", "unknown", "не знаю"])
def test_conflict_requires_explicit_resolution(answer):
    conflict = Conflict(id="size", title="Размер", options=["80 мм", "100 мм"], resolution=answer)
    result = assess(card(conflicts=[conflict]))
    assert "select_parameters" not in result.allowed_actions
    assert result.conflicts[0].resolved is False


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("nominal", "peak"),
        ("ambient", "brief_contact"),
        ("shaft", "overall"),
        ("wet", "dry"),
        ("20C", "80C"),
    ],
)
def test_different_conditions_are_not_conflicts(left, right):
    assert not comparable(
        Requirement(key="load", value="25", conditions=left),
        Requirement(key="load", value="75", conditions=right),
    )


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1,2", "g/cm3", "1200"),
        ("10", "cm", "100"),
        ("1", "m", "1000"),
        ("25.4", "mm", "25.4"),
        ("18", "kg", "18"),
    ],
)
def test_normalization_preserves_quantity_kind(value, unit, expected):
    assert normalize_quantity(value, unit)[0] == expected


@pytest.mark.parametrize(
    "left,right", [("10", "100"), ("1", "10"), ("0.1", "1"), ("12.5", "125"), ("2,5", "25")]
)
def test_T08_equivalent_centimeters_and_millimeters_do_not_conflict(left, right):
    from src.backend.domain.evidence import merge_cards

    result = merge_cards(
        [
            card(
                requirements=[
                    Requirement(key="size", value=left, unit="cm"),
                    Requirement(key="size", value=right, unit="mm"),
                ]
            )
        ]
    )
    assert not result.conflicts


@pytest.mark.parametrize(
    "question_id", ["model_units", "stl_units", "geometry_units", "stl.units", "model_unit"]
)
@pytest.mark.parametrize("units", ["unknown", "mm"])
def test_T07_model_units_question_uses_one_authoritative_fact(question_id, units):
    from src.backend.domain.models import Question

    result = assess(
        card(
            geometry=Geometry(readable=True, units=units),
            questions=[
                Question(id=question_id, title="В каких единицах STL?", reason="Нужен масштаб")
            ],
        )
    )
    assert len(result.questions) == (1 if units == "unknown" else 0)
    if result.questions:
        assert result.questions[0].id == "geometry.units"
        assert result.questions[0].options == ["mm", "cm", "m", "inch"]
