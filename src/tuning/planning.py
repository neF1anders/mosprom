"""Turn fired rules into a plan: per parameter a shift and an allowed interval of t, discrete choices, mode votes.

The start point is not part of the plan: it is the value the slicer would use anyway (quality profile, material,
definition) and is known only once the quality profile is chosen, see `resolve_t`.
"""

from typing import Any  # noqa: F401  (used in type comments)

from tuning.rules import resolve_value
from tuning.space import resolve_number, t_interval_for_limits

_EPSILON = 1e-9


def new_plan(params):
    # type: (dict) -> dict
    entries = {  # type: dict
        param_id: {
            "shift": 0.0,
            "lo": 0.0,
            "hi": 1.0,
            "rule_ids": [],
            "moving_rule_ids": [],
            "lo_rule": None,
            "hi_rule": None,
        }
        for param_id in params
    }
    return {
        "params": entries,
        "discrete": {},
        "banned": {},
        "allowed": {},
        "restricted_by": {},
        "votes": [],
        "min_layers": {},
        "unsatisfied": [],
        "conflicts": [],
    }


def build_plan(fired, params, facts, context):
    # type: (list, dict, dict, dict) -> dict
    """params: {id: Param}. Fired rules in file order; later actions win for discrete choices."""
    plan = new_plan(params)
    for rule in fired:
        for action in rule["then"]:
            _apply(action, rule["id"], plan, params, facts, context)
    return plan


def limit_param(plan, param, rule_id, minimum, maximum):
    # type: (dict, Any, str, Any, Any) -> None
    """Hard limits in the value domain (None = open), e.g. from a rule or a validator constraint."""
    entry = plan["params"][param.id]
    low, high = t_interval_for_limits(param, minimum, maximum)
    _raise_low(entry, rule_id, low)
    _lower_high(entry, rule_id, high)
    _touch(entry, rule_id, False)


def find_conflicts(plan):
    # type: (dict) -> list
    conflicts = []
    for param_id, entry in sorted(plan["params"].items()):
        if entry["lo"] > entry["hi"] + _EPSILON:
            conflicts.append({"param": param_id, "rules": sorted(set([entry["lo_rule"], entry["hi_rule"]]))})
    return conflicts


def resolve_t(entry, baseline_t):
    # type: (dict, float) -> tuple
    """(t, rule that decided it or None). The slicer value is first brought inside the hard interval, then
    shifted by the rules, then kept inside the interval again; a limit that cut the shift decides the value.
    A conflicting interval collapses to its middle."""
    low, high = entry["lo"], entry["hi"]
    if low > high:
        low = high = (low + high) / 2.0
    start = min(max(baseline_t, low), high)
    raw = start + entry["shift"]
    t = min(max(raw, low), high)
    if raw > high + _EPSILON and entry["hi_rule"]:
        return t, entry["hi_rule"]
    if raw < low - _EPSILON and entry["lo_rule"]:
        return t, entry["lo_rule"]
    if entry["moving_rule_ids"] and abs(entry["shift"]) > _EPSILON:
        return t, entry["moving_rule_ids"][-1]
    if abs(start - baseline_t) > _EPSILON:
        return t, entry["lo_rule"] if baseline_t < low else entry["hi_rule"]
    return t, None


def _touch(entry, rule_id, moves):
    if rule_id not in entry["rule_ids"]:
        entry["rule_ids"].append(rule_id)
    if moves and rule_id not in entry["moving_rule_ids"]:
        entry["moving_rule_ids"].append(rule_id)


def _raise_low(entry, rule_id, bound):
    if bound > entry["lo"]:
        entry["lo"], entry["lo_rule"] = bound, rule_id


def _lower_high(entry, rule_id, bound):
    if bound < entry["hi"]:
        entry["hi"], entry["hi_rule"] = bound, rule_id


def _apply(action, rule_id, plan, params, facts, context):
    operation = action["op"]
    if operation == "shift":
        entry = plan["params"][action["param"]]
        entry["shift"] += action["delta"]
        _touch(entry, rule_id, True)
    elif operation == "bound":
        entry = plan["params"][action["param"]]
        if "min_t" in action:
            _raise_low(entry, rule_id, action["min_t"])
        if "max_t" in action:
            _lower_high(entry, rule_id, action["max_t"])
        _touch(entry, rule_id, False)
    elif operation == "limit":
        minimum = resolve_number(action["min"], context) if "min" in action else None
        maximum = resolve_number(action["max"], context) if "max" in action else None
        limit_param(plan, params[action["param"]], rule_id, minimum, maximum)
    elif operation == "min_layers":
        plan["min_layers"][action["param"]] = {"min": action["min"], "rule_id": rule_id}
    elif operation == "set_discrete":
        plan["discrete"][action["param"]] = {"value": action["value"], "rule_id": rule_id}
    elif operation == "mode_vote":
        plan["votes"].append(
            {"mode": resolve_value(action["mode"], facts), "weight": action["weight"], "rule_id": rule_id}
        )
    elif operation == "unsatisfied":
        plan["unsatisfied"].append(
            {"requirement_key": action["requirement_key"], "why": action["why"], "rule_id": rule_id}
        )
