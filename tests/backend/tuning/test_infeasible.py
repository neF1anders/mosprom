from stage1_factory import constraint, feedback, handoff, requirement


def test_incompatible_hard_requirements_give_infeasible_with_the_pair(select):
    payload = handoff(requirements=[requirement("flexible", "да"), requirement("high_stiffness", "да")])
    code, parameter_set, err = select(payload)
    assert code == 0, err
    assert parameter_set["status"] == "infeasible"
    pairs = [
        (item["requirement_id"], item["conflicts_with"])
        for item in parameter_set["unsatisfied"]
        if "conflicts_with" in item
    ]
    assert pairs == [("flexible", "high_stiffness")]


def test_constraint_against_a_hard_requirement_gives_infeasible_with_both_sides(select):
    payload = handoff(requirements=[requirement("high_stiffness", "да")])
    code, parameter_set, err = select(payload, feedback(constraint("C1", "infill_sparse_density", "max", 20)))
    assert code == 0, err
    assert parameter_set["status"] == "infeasible"
    conflict = [item for item in parameter_set["unsatisfied"] if "conflicts_with" in item]
    assert [(item["requirement_id"], item["conflicts_with"]) for item in conflict] == [
        ("high_stiffness", "constraint:C1")
    ]
