"""Rule engine: conditions and actions are JSON data, see rules.json."""

import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.serialization import load_json_file

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
_COMPARISONS = {
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
    "in": lambda left, right: left in right,
}


def load_rules():
    # type: () -> list
    return load_json_file(_PATH)["rules"]


def holds(condition, facts):
    # type: (dict, dict) -> bool
    """Evaluate a condition tree; an empty condition always holds, an absent fact never does."""
    if not condition:
        return True
    if "all" in condition:
        return all(holds(item, facts) for item in condition["all"])
    if "any" in condition:
        return any(holds(item, facts) for item in condition["any"])
    if "not" in condition:
        return not holds(condition["not"], facts)
    fact = condition["fact"]
    if condition["op"] == "exists":
        return fact in facts
    if fact not in facts:
        return False
    return _COMPARISONS[condition["op"]](facts[fact], condition["value"])


def fired_rules(rules, facts):
    # type: (list, dict) -> list
    return [rule for rule in rules if holds(rule["when"], facts)]


def resolve_value(spec, facts):
    # type: (Any, dict) -> Any
    """Literal or {"ref": fact_name}."""
    if isinstance(spec, dict):
        return facts[spec["ref"]]
    return spec


def requirement_keys(rule):
    # type: (dict) -> list
    """Requirement keys a rule reads (from req.* / reqhard.* facts), sorted."""
    found = set()

    def walk(node):
        if "fact" in node:
            prefix, _, key = node["fact"].partition(".")
            if prefix in ("req", "reqhard"):
                found.add(key)
            return
        for child in node.get("all", []) + node.get("any", []):
            walk(child)
        if "not" in node:
            walk(node["not"])

    walk(rule["when"])
    return sorted(found)
