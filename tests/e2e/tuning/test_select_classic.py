import json

from tuning.catalog import read_materials
from tuning.contracts import param_set_errors
from tuning.hard_rules import hard_rule_violations
from tuning.space import load_profile

HARD_CARD = {
    "requirements": [
        {"id": "R1", "kind": "thermal", "key": "tg_min_c", "value": 85, "hard": True, "source": "user"},
        {"id": "R2", "kind": "mech", "key": "high_stiffness", "value": True, "hard": False, "source": "user"},
        {"id": "R3", "kind": "accuracy", "key": "dimensional_tol_mm", "value": 0.15, "hard": True, "source": "user"},
    ],
    "preferences": {"priority": ["strength", "accuracy"]},
}


def test_card_and_stl_give_explained_classic_parameters(run_tuning, write_card, mushroom_stl, materials_dir):
    code, out, err = run_tuning("select", "--card", write_card(**HARD_CARD), "--stl", mushroom_stl)
    assert code == 0, err
    param_set = json.loads(out)
    assert param_set_errors(param_set) == []
    assert param_set["status"] == "proposed"
    assert param_set["printing_mode"]["value"] == "classic"
    keys = {setting["key"]: setting for setting in param_set["settings"]}
    assert "classic_layer_height" in keys and "cylindrical_layer_height" not in keys
    assert keys["support_enable_classic"]["value"] is True
    assert keys["classic_layer_height"]["value"] <= 0.17  # tolerance rule: t >= 0.7
    material = read_materials(materials_dir, load_profile()["filament_mm"])[param_set["material"]["value"]]
    assert hard_rule_violations(param_set, load_profile(), material) == []


def test_named_material_from_card_is_used_with_source_card(run_tuning, write_card, block_stl):
    card = write_card(material={"name": "enduse_pa6", "source": "user"}, **HARD_CARD)
    code, out, err = run_tuning("select", "--card", card, "--stl", block_stl)
    assert code == 0, err
    material = json.loads(out)["material"]
    assert material["value"] == "enduse_pa6" and material["source"] == "card"


def test_unknown_card_fields_are_ignored_with_a_warning(run_tuning, write_card, block_stl):
    code, out, err = run_tuning("select", "--card", write_card(future_field=1), "--stl", block_stl)
    assert code == 0, err
    assert "unknown card field 'future_field' ignored" in json.loads(out)["warnings"]


def test_card_that_is_not_ready_is_rejected(run_tuning, write_card, block_stl):
    code, out, err = run_tuning("select", "--card", write_card(status="needs_input"), "--stl", block_stl)
    assert code == 2 and "status" in err
