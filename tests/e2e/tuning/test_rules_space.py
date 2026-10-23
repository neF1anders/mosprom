import json
import os

import pytest

from tuning.rules import load_rules
from tuning.rules.engine import holds
from tuning.space import Param, load_profile, load_search_space, t_interval_for_limits

CONTEXT = {"profile": load_profile(), "material": {"print_temperature": 250.0, "speed": 50.0}}
KNOWN_OPS = {"shift", "bound", "limit", "min_layers", "set_discrete", "mode_vote", "unsatisfied"}


def params():
    return {d["id"]: Param(d, CONTEXT) for d in load_search_space()["params"]}


def test_rule_ids_are_unique_and_actions_known():
    rules = load_rules()
    assert len(set(rule["id"] for rule in rules)) == len(rules)
    for rule in rules:
        assert rule["reason"] and rule["source"]
        assert all(action["op"] in KNOWN_OPS for action in rule["then"])


def test_condition_tree_semantics():
    facts = {"a": 3, "flag": True}
    assert holds({}, facts)
    assert holds({"fact": "a", "op": ">", "value": 2}, facts)
    assert not holds({"fact": "missing", "op": ">", "value": 2}, facts)
    assert holds({"fact": "missing", "op": "exists"}, {"missing": 0})
    assert holds({"not": {"fact": "a", "op": "==", "value": 4}}, facts)
    assert holds({"any": [{"fact": "a", "op": "<", "value": 0}, {"fact": "flag", "op": "==", "value": True}]}, facts)
    assert not holds({"all": [{"fact": "a", "op": "in", "value": [1, 2]}]}, facts)


def test_axis_is_monotone_and_hits_both_ends():
    layer = params()["layer_height"]
    assert layer.value_at(0.0) == 0.32 and layer.value_at(1.0) == 0.1
    values = [layer.value_at(t / 10.0) for t in range(11)]
    assert values == sorted(values, reverse=True)
    assert params()["print_speed"].value_at(1.0) == 25


def test_value_limits_become_t_intervals_for_both_axis_directions():
    layer, density = params()["layer_height"], params()["infill_density"]
    low, high = t_interval_for_limits(layer, 0.1, 0.32)
    assert (low, high) == (pytest.approx(0.0, abs=1e-9), 1.0)
    low, high = t_interval_for_limits(layer, None, 0.2)
    assert low == pytest.approx(0.5454, abs=1e-3) and high == 1.0
    assert t_interval_for_limits(density, 30, None) == (0.4, 1.0)


@pytest.mark.skipif(not os.environ.get("STE_DEFINITIONS_DIR"), reason="STE Slicer resources/definitions not available")
def test_every_emitted_key_exists_in_slicer_definitions():
    with open(os.path.join(os.environ["STE_DEFINITIONS_DIR"], "fdmprinter.def.json"), encoding="utf-8") as stream:
        definitions = json.load(stream)
    known = set()

    def walk(node):
        for key, value in node.items():
            known.add(key)
            walk(value.get("children", {}))

    walk(definitions["settings"])
    space = load_search_space()
    emitted = set()
    for item in space["params"] + space["discrete"]:
        for keys in item.get("keys", {}).values():
            emitted.update(keys)
        emitted.update(item.get("emit", {}).get("keys", []))
    assert emitted - known == set()
