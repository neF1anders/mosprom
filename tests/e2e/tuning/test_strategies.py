import pytest
from loop_helpers import advance, issue, setting, start

CARD = {"part": {"load": "static"}, "preferences": {"priority": ["strength"]}}
WEAK = {"ok": False, "score": 0.3, "issues": [issue("infill_sparse_density", "too_weak", severity=0.8)]}


def run_weak_steps(run_tuning, write_card, stl, tmp_path, strategy, steps):
    card = write_card(**CARD)
    extra = ("--strategy", strategy, "--max-iterations", "10")
    result, state = start(run_tuning, tmp_path, card, stl, *extra)
    densities = [setting(result, "infill_sparse_density")["value"]]
    for number in range(1, steps + 1):
        result, state = advance(run_tuning, tmp_path, card, stl, state, WEAK, number, *extra)
        assert result["status"] in ("proposed", "infeasible")
        densities.append(setting(result, "infill_sparse_density")["value"])
    return densities


@pytest.mark.parametrize("strategy", ["m1", "m2", "m3"])
def test_repeated_too_weak_raises_the_signalled_parameter_without_decreasing_it(
    run_tuning, write_card, block_stl, tmp_path, strategy
):
    densities = run_weak_steps(run_tuning, write_card, block_stl, tmp_path, strategy, 3)
    assert densities == sorted(densities) and densities[-1] > densities[0]


def test_m2_takes_a_bigger_first_step_for_a_severe_issue_than_m1(run_tuning, write_card, block_stl, tmp_path):
    (tmp_path / "a").mkdir()
    m1 = run_weak_steps(run_tuning, write_card, block_stl, tmp_path / "a", "m1", 1)
    m2 = run_weak_steps(run_tuning, write_card, block_stl, tmp_path, "m2", 1)
    assert m2[1] >= m1[1]


def test_m3_moves_other_parameters_together_with_lambda(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    first, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m3")
    second, _ = advance(run_tuning, tmp_path, card, block_stl, state, WEAK, 1, "--strategy", "m3")
    assert setting(second, "wall_line_count")["value"] >= setting(first, "wall_line_count")["value"]
    assert second["settings"] != first["settings"]
    assert setting(second, "wall_line_count")["source"].startswith("search:") or setting(
        second, "classic_layer_height"
    )["source"].startswith("search:")


def test_m4_tries_strong_candidate_then_fast_then_refines(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    extra = ("--strategy", "m4", "--max-iterations", "10")
    balance, state = start(run_tuning, tmp_path, card, block_stl, *extra)
    # The verdict passed at step k judges the proposal of step k-1: balance 0.4, strong 0.6, fast 0.2.
    strong, state = advance(run_tuning, tmp_path, card, block_stl, state, dict(WEAK, score=0.4), 1, *extra)
    fast, state = advance(run_tuning, tmp_path, card, block_stl, state, dict(WEAK, score=0.6), 2, *extra)
    refined, _ = advance(run_tuning, tmp_path, card, block_stl, state, dict(WEAK, score=0.2), 3, *extra)

    def density(param_set):
        return setting(param_set, "infill_sparse_density")["value"]

    assert density(fast) < density(balance) < density(strong)
    assert density(balance) < density(refined) < density(strong)


def test_m5_holds_a_parameter_blamed_both_ways_while_m1_gives_up(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    mixed = {
        "ok": False,
        "issues": [
            issue("infill_sparse_density", "too_weak", 1),
            issue("infill_sparse_density", "too_costly", 2),
            issue("wall_line_count", "too_weak", 3),
        ],
    }
    outcomes = {}
    for strategy in ("m1", "m5"):
        folder = tmp_path / strategy
        folder.mkdir()
        first, state = start(run_tuning, folder, card, block_stl, "--strategy", strategy)
        outcomes[strategy] = (
            first,
            advance(run_tuning, folder, card, block_stl, state, mixed, 1, "--strategy", strategy)[0],
        )
    assert outcomes["m1"][1]["status"] == "infeasible"
    first, second = outcomes["m5"]
    assert second["status"] == "proposed"
    assert setting(second, "infill_sparse_density")["value"] == setting(first, "infill_sparse_density")["value"]
    assert setting(second, "wall_line_count")["value"] > setting(first, "wall_line_count")["value"]


def test_m5_keeps_moving_other_parameters_when_one_is_stuck_at_its_bound(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(
        requirements=[
            {"id": "R1", "kind": "x", "key": "no_visible_layers", "value": True, "hard": True, "source": "user"}
        ]
    )
    extra = ("--strategy", "m5", "--max-iterations", "10")
    result, state = start(run_tuning, tmp_path, card, block_stl, *extra)
    verdict = {
        "ok": False,
        "issues": [issue("classic_layer_height", "too_weak", 1), issue("wall_line_count", "too_weak", 2)],
    }
    walls = []
    for number in range(1, 13):
        result, state = advance(run_tuning, tmp_path, card, block_stl, state, verdict, number, *extra)
        if result["status"] != "proposed":
            break
        walls.append(setting(result, "wall_line_count")["value"])
    # It only gives up once every signalled parameter is stuck, after walls were pushed up to their limit.
    assert result["status"] == "infeasible"
    assert setting(result, "classic_layer_height")["value"] == 0.1 and walls[-1] == 6 and walls[0] < walls[-1]
