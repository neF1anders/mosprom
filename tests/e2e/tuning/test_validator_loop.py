from loop_helpers import advance, issue, setting, start

CARD = {"part": {"load": "static"}, "preferences": {"priority": ["strength"]}}


def test_verdict_produces_next_iteration_that_follows_the_signal(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    first, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m1")
    weak = {"ok": False, "issues": [issue("infill_sparse_density", "too_weak")]}
    second, state = advance(run_tuning, tmp_path, card, block_stl, state, weak, 1, "--strategy", "m1")
    assert second["status"] == "proposed" and second["iteration"] == 1
    assert setting(second, "infill_sparse_density")["value"] > setting(first, "infill_sparse_density")["value"]
    assert setting(second, "infill_sparse_density")["source"] == "search:it1"
    assert setting(second, "wall_line_count")["value"] == setting(first, "wall_line_count")["value"]
    costly = {"ok": False, "issues": [issue("infill_sparse_density", "too_costly")]}
    third, _ = advance(run_tuning, tmp_path, card, block_stl, state, costly, 2, "--strategy", "m1")
    between = (setting(first, "infill_sparse_density")["value"], setting(second, "infill_sparse_density")["value"])
    assert between[0] < setting(third, "infill_sparse_density")["value"] < between[1]


def test_ok_verdict_gives_final_with_the_same_settings(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    first, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m1")
    final, _ = advance(run_tuning, tmp_path, card, block_stl, state, {"ok": True, "score": 0.9}, 1, "--strategy", "m1")
    assert final["status"] == "final"
    assert final["settings"] == first["settings"]


def test_budget_exhausted_is_reported_as_exhausted_with_reasons_never_final(
    run_tuning, write_card, block_stl, tmp_path
):
    card = write_card(**CARD)
    weak = {"ok": False, "score": 0.4, "issues": [issue("infill_sparse_density", "too_weak", requirement_id="R7")]}
    _, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m1", "--max-iterations", "2")
    second, state = advance(
        run_tuning, tmp_path, card, block_stl, state, weak, 1, "--strategy", "m1", "--max-iterations", "2"
    )
    assert second["status"] == "proposed"
    last, _ = advance(
        run_tuning,
        tmp_path,
        card,
        block_stl,
        state,
        dict(weak, score=0.5),
        2,
        "--strategy",
        "m1",
        "--max-iterations",
        "2",
    )
    assert last["status"] == "exhausted"
    assert {"requirement_id": "R7", "why": "validator: too_weak"} in last["unsatisfied"]
    assert last["iteration"] == 1  # the better-scored proposal is returned


def test_baseline_m0_does_not_revise_after_a_rejection(run_tuning, write_card, block_stl, tmp_path):
    card = write_card(**CARD)
    _, state = start(run_tuning, tmp_path, card, block_stl, "--strategy", "m0")
    weak = {"ok": False, "issues": [issue("infill_sparse_density", "too_weak")]}
    result, _ = advance(run_tuning, tmp_path, card, block_stl, state, weak, 1, "--strategy", "m0")
    assert result["status"] == "exhausted"


def test_veto_switches_a_discrete_setting_to_the_next_candidate(run_tuning, write_card, mushroom_stl, tmp_path):
    card = write_card(**CARD)
    first, state = start(run_tuning, tmp_path, card, mushroom_stl, "--strategy", "m1")
    assert setting(first, "support_enable_classic")["value"] is True
    verdict = {
        "ok": False,
        "vetoes": [{"key": "support_enable_classic", "value": True, "message": "supports leave marks"}],
    }
    second, _ = advance(run_tuning, tmp_path, card, mushroom_stl, state, verdict, 1, "--strategy", "m1")
    assert setting(second, "support_enable_classic")["value"] is False
    assert setting(second, "support_enable_classic")["source"] == "search:it1"
