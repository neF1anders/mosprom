"""Turn fired rules into a plan: start point and allowed interval per parameter, discrete choices, mode votes."""
from tuning.rules import resolve_value
from tuning.space import resolve_number, t_interval_for_limits

BASELINE_T = 0.5
_EPSILON = 1e-9


def build_plan(fired, params, facts, context):
    # type: (list, dict, dict, dict) -> dict
    """params: {id: Param}. Returns plan with `params`, `discrete`, `votes`, `min_layers`, `unsatisfied`, `conflicts`."""
    entries = {
        param_id: {"t0": BASELINE_T, "lo": 0.0, "hi": 1.0, "rule_ids": [], "moving_rule_ids": [],
                   "lo_rule": None, "hi_rule": None}
        for param_id in params
    }
    plan = {"params": entries, "discrete": {}, "votes": [], "min_layers": {}, "unsatisfied": [], "conflicts": []}
    for rule in fired:
        for action in rule["then"]:
            _apply(action, rule, plan, params, facts, context)
    for param_id, entry in sorted(entries.items()):
        if entry["lo"] > entry["hi"] + _EPSILON:
            plan["conflicts"].append({"param": param_id, "rules": sorted(set([entry["lo_rule"], entry["hi_rule"]]))})
            middle = (entry["lo"] + entry["hi"]) / 2.0
            entry["lo"] = entry["hi"] = min(max(middle, 0.0), 1.0)
        entry["t0"] = min(max(entry["t0"], entry["lo"]), entry["hi"])
    return plan


def _touch(entry, rule, moves):
    if rule["id"] not in entry["rule_ids"]:
        entry["rule_ids"].append(rule["id"])
    if moves and rule["id"] not in entry["moving_rule_ids"]:
        entry["moving_rule_ids"].append(rule["id"])


def _raise_low(entry, rule, bound):
    if bound > entry["lo"]:
        entry["lo"], entry["lo_rule"] = bound, rule["id"]


def _lower_high(entry, rule, bound):
    if bound < entry["hi"]:
        entry["hi"], entry["hi_rule"] = bound, rule["id"]


def _apply(action, rule, plan, params, facts, context):
    operation = action["op"]
    if operation == "shift":
        entry = plan["params"][action["param"]]
        entry["t0"] += action["delta"]
        _touch(entry, rule, True)
    elif operation == "bound":
        entry = plan["params"][action["param"]]
        if "min_t" in action:
            _raise_low(entry, rule, action["min_t"])
        if "max_t" in action:
            _lower_high(entry, rule, action["max_t"])
        _touch(entry, rule, True)
    elif operation == "limit":
        param = params[action["param"]]
        entry = plan["params"][action["param"]]
        minimum = resolve_number(action["min"], context) if "min" in action else None
        maximum = resolve_number(action["max"], context) if "max" in action else None
        low, high = t_interval_for_limits(param, minimum, maximum)
        _raise_low(entry, rule, low)
        _lower_high(entry, rule, high)
        _touch(entry, rule, False)
    elif operation == "min_layers":
        for key in action["keys"]:
            plan["min_layers"][key] = max(plan["min_layers"].get(key, 0), action["min"])
        plan["min_layers_rule"] = rule["id"]
    elif operation == "set_discrete":
        plan["discrete"][action["param"]] = {"value": action["value"], "rule_id": rule["id"], "reason": rule["reason"]}
    elif operation == "mode_vote":
        plan["votes"].append({
            "mode": resolve_value(action["mode"], facts), "weight": action["weight"],
            "confidence": action["confidence"], "rule_id": rule["id"], "reason": rule["reason"],
        })
    elif operation == "unsatisfied":
        plan["unsatisfied"].append({"requirement_key": action["requirement_key"], "why": action["why"], "rule_id": rule["id"]})
