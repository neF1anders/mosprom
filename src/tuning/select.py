"""select_parameters: task card + geometry -> param_set/0 with a reason for every value."""
import math
import os

from tuning.catalog import read_materials
from tuning.contracts import normalize_card, validate_verdict
from tuning.errors import TuningError
from tuning.facts import build_facts
from tuning.hard_rules import fits_build_volume
from tuning.material_choice import choose_material
from tuning.planning import build_plan
from tuning.rules import fired_rules, load_rules, requirement_keys
from tuning.space import Param, load_profile, load_search_space
from tuning.strategies import get_strategy

DEFAULT_CONFIG = {"strategy": "m0", "seed": 1, "max_iterations": 3, "materials_dir": None}
STATE_SCHEMA = "tuning_state/0"


def select_parameters(card, geometry, state=None, verdict=None, config=None):
    # type: (dict, dict, object, object, object) -> tuple
    """First call: state=None, verdict=None. Returns (param_set, new_state), both JSON-compatible."""
    settings = dict(DEFAULT_CONFIG)
    settings.update(config or {})
    if verdict is not None:
        validate_verdict(verdict)
        raise TuningError("verdict handling is not available yet")
    card, warnings = normalize_card(card)
    materials = read_materials(_materials_dir(settings))
    profile, space, rules = load_profile(), load_search_space(), load_rules()

    choice, material_warnings = choose_material(card, materials)
    warnings.extend(material_warnings)
    material = choice.material
    if material.print_temperature is None:
        raise TuningError("material '%s' has no print temperature in the catalog" % material.id)
    context = {"profile": profile, "material": material.context()}
    params = {definition["id"]: Param(definition, context) for definition in space["params"]}
    facts = build_facts(card, geometry)
    fired = fired_rules(rules, facts)
    plan = build_plan(fired, params, facts, context)

    unsatisfied = list(choice.unsatisfied)
    mode_block, mode_unsatisfied = _choose_mode(plan["votes"], geometry, profile, warnings)
    unsatisfied.extend(mode_unsatisfied)
    mode = mode_block["value"]

    strategy = get_strategy(settings["strategy"])
    points, strategy_state = strategy.propose(plan["params"], {}, None, 0)
    rule_reasons = {rule["id"]: rule["reason"] for rule in rules}
    entries = _settings(mode, params, points, plan, space, material, profile, rule_reasons)

    key_ids = _requirement_ids_by_key(card)
    unsatisfied.extend(_plan_unsatisfied(plan, rules, key_ids))
    infeasible = choice.infeasible or bool(plan["conflicts"]) or bool(mode_unsatisfied)
    param_set = {
        "schema": "param_set/0",
        "iteration": 0,
        "strategy": strategy.id,
        "status": "infeasible" if infeasible else "proposed",
        "printing_mode": mode_block,
        "material": choice.block,
        "settings": entries,
        "orientation": None,
        "assumptions_used": choice.assumptions,
        "unsatisfied": unsatisfied,
        "warnings": warnings,
        "build_volume_mm": _build_volume(profile, mode),
    }
    new_state = {
        "schema": STATE_SCHEMA, "iteration": 0, "strategy": strategy.id, "seed": settings["seed"],
        "material": material.id, "mode": mode, "strategy_state": strategy_state, "history": [],
    }
    return param_set, new_state


def _materials_dir(settings):
    directory = settings["materials_dir"] or os.environ.get("STE_MATERIALS_DIR")
    if not directory:
        raise TuningError("materials directory is not set: pass --materials-dir or set STE_MATERIALS_DIR")
    if not os.path.isdir(directory):
        raise TuningError("materials directory does not exist: %s" % directory)
    return directory


def _build_volume(profile, mode):
    volume = profile["build_volume_mm"]
    return {"width": volume["width"], "depth": volume["depth"], "height": volume["height"][mode]}


def _choose_mode(votes, geometry, profile, warnings):
    # type: (list, dict, dict, list) -> tuple
    size = geometry["bbox_mm"]["size"]
    valid = [v for v in votes if v["mode"] in profile["modes"]]
    for vote in votes:
        if vote["mode"] not in profile["modes"]:
            warnings.append("printing mode '%s' from rule %s is unknown, ignored" % (vote["mode"], vote["rule_id"]))
    weights = {}
    for vote in valid:
        if fits_build_volume(size, profile, vote["mode"]):
            weights[vote["mode"]] = weights.get(vote["mode"], 0.0) + vote["weight"]
    if not weights:
        fallback = "classic"
        return ({"value": fallback, "source": "default:" + profile["id"], "confidence": 0.1,
                 "reason": "model does not fit the build volume in any mode as oriented; classic kept as placeholder"},
                [{"requirement_id": "GEOMETRY", "why": "model size %s mm exceeds the build volume in every mode (orientation not searched)" % size}])
    winner = max(sorted(weights), key=lambda mode: weights[mode])
    top = max((v for v in valid if v["mode"] == winner), key=lambda v: (v["weight"], v["rule_id"]))
    source = "card" if top["rule_id"] == "mode-card-hint" else "rule:" + top["rule_id"]
    return {"value": winner, "source": source, "reason": top["reason"], "confidence": top["confidence"]}, []


def _requirement_ids_by_key(card):
    ids = {}
    for requirement in card.get("requirements", []):
        ids.setdefault(requirement["key"], []).append(requirement["id"])
    return ids


def _plan_unsatisfied(plan, rules, key_ids):
    by_id = {rule["id"]: rule for rule in rules}

    def reference(rule_id):
        found = [i for key in requirement_keys(by_id[rule_id]) for i in key_ids.get(key, [])]
        return found[0] if found else "rule:" + rule_id

    result = []
    for item in plan["unsatisfied"]:
        for requirement_id in key_ids.get(item["requirement_key"], ["rule:" + item["rule_id"]]):
            result.append({"requirement_id": requirement_id, "why": item["why"]})
    for conflict in plan["conflicts"]:
        first, second = (conflict["rules"] + conflict["rules"])[:2]
        result.append({"requirement_id": reference(first), "conflicts_with": reference(second),
                       "why": "rules %s and %s demand incompatible values of %s" % (first, second, conflict["param"])})
    return result


def _explain(entry, rule_reasons, profile_id):
    if entry["moving_rule_ids"]:
        moving = entry["moving_rule_ids"]
        return "rule:" + moving[-1], "; ".join(rule_reasons[rule_id] for rule_id in moving)
    return "default:" + profile_id, "mid-range starting point; no rule moved this parameter"


def _settings(mode, params, points, plan, space, material, profile, rule_reasons):
    values = {param_id: params[param_id].value_at(points[param_id]) for param_id in params}
    entries = []

    def add(key, value, unit, t, source, rule_ids, reason):
        entries.append({"key": key, "value": value, "unit": unit, "target": "global", "t": t,
                        "source": source, "rule_ids": sorted(rule_ids), "reason": reason})

    for param_id, param in sorted(params.items()):
        entry = plan["params"][param_id]
        source, reason = _explain(entry, rule_reasons, profile["id"])
        t = round(points[param_id], 4)
        if param.emit:
            layer = values[param.emit["layer_param"]]
            for key in param.emit["keys"]:
                layers = max(plan["min_layers"].get(key, 0), int(math.ceil(round(values[param_id] / layer, 4))))
                add(key, layers, "", t, source, entry["rule_ids"] + [plan["min_layers_rule"]],
                    "%s; %g mm of solid skin at %g mm layers" % (reason, values[param_id], layer))
            continue
        for key in param.keys[mode]:
            add(key, values[param_id], param.unit, t, source, entry["rule_ids"], reason)

    density = values["infill_density"]
    for definition in space["discrete"]:
        keys = definition["keys"][mode]
        if not keys:
            continue
        chosen = plan["discrete"].get(definition["id"])
        if "from_material" in definition:
            value = getattr(material, definition["from_material"])
            if value is None:
                continue
            source, rule_ids, reason = "default:material:" + material.id, [], "value from the material file"
        elif chosen:
            value, source, rule_ids, reason = chosen["value"], "rule:" + chosen["rule_id"], [chosen["rule_id"]], chosen["reason"]
        else:
            value = definition["default"]
            if definition["id"] == "infill_pattern":
                value = definition["default_dense"] if density > definition["dense_above_pct"] else definition["default"]
            source, rule_ids, reason = "default:" + profile["id"], [], "profile default; no rule fired"
        for key in keys:
            add(key, value, definition["unit"], None, source, rule_ids, reason)
    return sorted(entries, key=lambda item: item["key"])
