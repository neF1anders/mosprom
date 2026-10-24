import pytest

from tests.backend.tuning.cards import card, constraint, feedback, requirement

pytestmark = pytest.mark.unit


def pairs(parameter_set):
    return [
        (item["requirement_id"], item["conflicts_with"])
        for item in parameter_set["unsatisfied"]
        if "conflicts_with" in item
    ]


def test_incompatible_hard_requirements_give_infeasible_with_the_pair(select):
    stiff_and_soft = card(
        requirements=[requirement("flexible", "да"), requirement("high_stiffness", "да")]
    )
    parameter_set = select(stiff_and_soft)
    assert parameter_set["status"] == "infeasible"
    assert pairs(parameter_set) == [("flexible", "high_stiffness")]


def test_constraint_against_a_hard_requirement_gives_infeasible_with_both_sides(select):
    stiff = card(requirements=[requirement("high_stiffness", "да")])
    parameter_set = select(stiff, feedback(constraint("C1", "infill_sparse_density", "max", 20)))
    assert parameter_set["status"] == "infeasible"
    assert pairs(parameter_set) == [("high_stiffness", "constraint:C1")]


def test_constraint_beyond_the_search_range_gives_infeasible_without_a_crash(select):
    # The axis of infill ends at 60 %: the minimum empties the interval with no rule on the
    # other side. The original code sorted [rule, None] here and raised a TypeError.
    parameter_set = select(card(), feedback(constraint("C1", "infill_sparse_density", "min", 70)))
    assert parameter_set["status"] == "infeasible"
    (item,) = parameter_set["unsatisfied"]
    assert item["requirement_id"] == "constraint:C1" and "conflicts_with" not in item
    assert parameter_set["settings"]["infill_sparse_density"]["value"] == 60
