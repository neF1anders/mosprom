def test_same_input_and_seed_give_identical_bytes(run_tuning, write_card, mushroom_stl, tmp_path):
    card = write_card(preferences={"priority": ["speed"]}, part={"load": "impact"})
    first = run_tuning(
        "select", "--card", card, "--stl", mushroom_stl, "--seed", "7", "--state-out", str(tmp_path / "a.json")
    )
    second = run_tuning(
        "select", "--card", card, "--stl", mushroom_stl, "--seed", "7", "--state-out", str(tmp_path / "b.json")
    )
    assert first[0] == 0 and first[1] == second[1]
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
