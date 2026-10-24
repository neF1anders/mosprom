import configparser
import glob
import json
import os
import re

import pytest

from tuning.constraints import wall_lines
from tuning.rules import load_rules
from tuning.rules.engine import holds
from tuning.space import Param, load_profile, load_search_space, t_interval_for_limits

PROFILE = load_profile()
CONTEXT = {
    "profile": PROFILE,
    "material": {"print_temperature": 250.0, "speed": 50.0, "speed_floor": 25.0},
    "limits": {"temperature_max_c": 285.0},
}
KNOWN_OPS = {"shift", "bound", "limit", "min_layers", "set_discrete", "mode_vote", "unsatisfied"}
# Resources of the issued STE Slicer 5.2.4 build (validation/resources/ste_5.2.4 of the stage-3 branch).
RESOURCES = os.environ.get("STE_RESOURCES_DIR")


def params():
    return {d["id"]: Param(d, CONTEXT) for d in load_search_space()["params"]}


def test_rule_ids_fit_the_source_pattern_of_the_contract():
    rules = load_rules()
    assert len(set(rule["id"] for rule in rules)) == len(rules)
    for rule in rules:
        assert re.match(r"^[\w\-.]+$", rule["id"]), rule["id"]
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


def test_axes_are_monotone_from_cheap_to_strong():
    layer = params()["layer_height"]
    assert layer.value_at(0.0) == 0.32 and layer.value_at(1.0) == 0.06
    values = [layer.value_at(t / 10.0) for t in range(11)]
    assert values == sorted(values, reverse=True)
    assert params()["print_speed"].value_at(1.0) == 25


def test_value_limits_become_t_intervals_for_both_axis_directions():
    layer, density = params()["layer_height"], params()["infill_density"]
    low, high = t_interval_for_limits(layer, 0.1, 0.32)
    assert low == pytest.approx(0.0, abs=1e-9) and high == pytest.approx(0.8462, abs=1e-3)
    assert t_interval_for_limits(density, 30, None) == (0.4, 1.0)


@pytest.mark.parametrize("lines", [2, 3, 4, 5, 6])
def test_sent_wall_thickness_gives_back_the_intended_line_count(lines):
    assert wall_lines(round(lines * PROFILE["line_width_mm"], 4), PROFILE["line_width_mm"]) == lines


def test_quality_profile_fast_starts_from_its_own_walls_and_infill():
    fast = PROFILE["qualities"]["fast"]["values"]
    # 1 mm of wall at 0.4 mm lines: the slicer formula rounds 1.4999... down, so the profile prints 2 walls.
    assert wall_lines(fast["wall_thickness"], PROFILE["line_width_mm"]) == 2
    assert fast["infill_sparse_density"] == 10


def _flat_definitions(path):
    with open(path, encoding="utf-8") as stream:
        definitions = json.load(stream)
    flat = {}

    def walk(node):
        for key, value in node.items():
            flat[key] = value
            walk(value.get("children", {}))

    walk(definitions["settings"])
    return flat


@pytest.mark.skipif(not RESOURCES, reason="STE Slicer 5.2.4 resources not available (set STE_RESOURCES_DIR)")
def test_every_key_we_send_exists_in_the_issued_build():
    known = _flat_definitions(os.path.join(RESOURCES, "definitions", "fdmprinter.def.json"))
    space = load_search_space()
    keys = set(item["key"] for item in space["params"])
    for item in space["discrete"]:
        keys.update([item["key"]] if isinstance(item["key"], str) else [])
    keys.update(mode["fan_key"] for mode in PROFILE["modes"].values())
    assert keys - set(known) == set()


@pytest.mark.skipif(not RESOURCES, reason="STE Slicer 5.2.4 resources not available (set STE_RESOURCES_DIR)")
def test_profile_data_matches_the_issued_build():
    definitions = _flat_definitions(os.path.join(RESOURCES, "definitions", "fdmprinter.def.json"))
    for path in glob.glob(os.path.join(RESOURCES, "quality", "*.inst.cfg")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding="utf-8")
        name = parser.get("metadata", "quality_type")
        values = dict(parser.items("values"))
        # A profile without a layer height (normal = Fine) prints with the definition default.
        layer = float(values.pop("layer_height", definitions["layer_height"]["default_value"]))
        assert PROFILE["qualities"][name]["layer_height"] == layer
        for key, expected in PROFILE["qualities"][name]["values"].items():
            assert float(values[key]) == expected
    with open(os.path.join(RESOURCES, "definitions", "steprinter530_v5.2.4.def.json"), encoding="utf-8") as stream:
        printer = json.load(stream)["overrides"]
    assert printer["machine_width"]["default_value"] == PROFILE["width_mm"]
    assert printer["machine_depth"]["default_value"] == PROFILE["depth_mm"]
    assert "231.1" in printer["machine_height"]["value"]
    left, right = printer["machine_disallowed_areas"]["default_value"]
    assert PROFILE["modes"]["classic"]["usable_x_mm"] == [max(p[0] for p in left), min(p[0] for p in right)]
