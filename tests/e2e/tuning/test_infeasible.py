from loop_helpers import advance, issue, setting, start


def requirement(number, key, value):
    return {"id": "R%d" % number, "kind": "x", "key": key, "value": value, "hard": True, "source": "user"}


def test_incompatible_hard_requirements_give_infeasible_with_the_pair(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(requirements=[requirement(1, "flexible", True), requirement(2, "high_stiffness", True)])
    param_set, _ = start(run_tuning, tmp_path, card, block_stl)
    assert param_set["status"] == "infeasible"
    pairs = [item for item in param_set["unsatisfied"] if "conflicts_with" in item]
    assert [(item["requirement_id"], item["conflicts_with"]) for item in pairs] == [("R1", "R2")]


def test_infeasible_stays_infeasible_when_the_loop_continues(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(requirements=[requirement(1, "flexible", True), requirement(2, "high_stiffness", True)])
    _, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m1")
    again, _ = advance(run_tuning, tmp_path, card, block_stl, state, {"ok": False}, 1, "--strategy", "m1")
    assert again["status"] == "infeasible"


def test_validator_pulling_one_parameter_both_ways_gives_infeasible_with_the_pair(run_tuning, write_card, block_stl, tmp_path):
    card = write_card()
    _, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m1")
    verdict = {"ok": False, "issues": [
        issue("infill_sparse_density", "too_weak", 1, "R2"), issue("infill_sparse_density", "too_costly", 2, "R5")]}
    result, _ = advance(run_tuning, tmp_path, card, block_stl, state, verdict, 1, "--strategy", "m1")
    assert result["status"] == "infeasible"
    assert {"requirement_id": "R2", "conflicts_with": "R5", "why": "validator reports both too_weak and too_costly"} in result["unsatisfied"]


def test_hard_bound_reached_while_validator_wants_more_gives_infeasible(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(requirements=[requirement(1, "no_visible_layers", True)])
    extra = ("--strategy", "m1", "--max-iterations", "10")
    result, state = start(run_tuning, tmp_path, card, block_stl, *extra)
    verdict = {"ok": False, "issues": [issue("classic_layer_height", "too_weak", 1, "R1")]}
    for number in range(1, 10):
        result, state = advance(run_tuning, tmp_path, card, block_stl, state, verdict, number, *extra)
        if result["status"] != "proposed":
            break
    assert result["status"] == "infeasible"
    assert any("hard bound" in item["why"] or "bound" in item["why"] for item in result["unsatisfied"])
    assert setting(result, "classic_layer_height")["value"] == 0.1
