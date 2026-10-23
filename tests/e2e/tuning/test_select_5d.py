import json

NO_SUPPORTS = {"requirements": [{"id": "R1", "kind": "geometry", "key": "no_supports", "value": True, "hard": True, "source": "user"}]}


def keys_of(param_set):
    return {setting["key"]: setting for setting in param_set["settings"]}


def run_select(run_tuning, card, stl):
    code, out, err = run_tuning("select", "--card", card, "--stl", stl)
    assert code == 0, err
    return json.loads(out)


def test_5d_hint_uses_cylindrical_keys_and_5d_build_height(run_tuning, write_card, block_stl):
    param_set = run_select(run_tuning, write_card(preferences={"printing_mode": "cylindrical"}), block_stl)
    assert param_set["printing_mode"]["value"] == "cylindrical" and param_set["printing_mode"]["source"] == "card"
    keys = keys_of(param_set)
    assert "cylindrical_layer_height" in keys and "support_enable_cylindrical" in keys
    assert "classic_layer_height" not in keys and "support_enable_classic" not in keys
    assert param_set["build_volume_mm"]["height"] == 250.0


def test_cylindrical_full_emits_both_key_sets(run_tuning, write_card, block_stl):
    keys = keys_of(run_select(run_tuning, write_card(preferences={"printing_mode": "cylindrical_full"}), block_stl))
    assert "classic_layer_height" in keys and "cylindrical_layer_height" in keys


def test_forbidden_supports_with_overhangs_suggest_5d_as_a_hypothesis(run_tuning, write_card, mushroom_stl):
    param_set = run_select(run_tuning, write_card(**NO_SUPPORTS), mushroom_stl)
    mode = param_set["printing_mode"]
    assert mode["value"] == "cylindrical" and mode["source"] == "rule:mode-overhang"
    assert mode["confidence"] < 0.5
    assert [item["requirement_id"] for item in param_set["unsatisfied"]] == ["R1"]


def test_mode_that_cannot_hold_the_part_is_not_chosen(run_tuning, write_card, tall_stl):
    param_set = run_select(run_tuning, write_card(preferences={"printing_mode": "cylindrical"}), tall_stl)
    assert param_set["printing_mode"]["value"] == "classic"
