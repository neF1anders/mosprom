"""Apply stage-3 constraints: hard limits on searched axes, forced or banned discrete values, pass-through keys."""

from typing import Any  # noqa: F401  (used in type comments)

from tuning.planning import limit_param

# Keys that select the printing mode, the quality profile and the material rather than a slicer setting.
MODE_KEY, QUALITY_KEY, MATERIAL_KEY = "printing_mode", "quality_type", "material"


class Choices(object):
    """Forced, allowed and banned values for the three top-level choices."""

    def __init__(self):
        self.forced = {}  # type: dict
        self.allowed = {}  # type: dict
        self.banned = {}  # type: dict

    def restrict(self, name, constraint):
        # type: (str, dict) -> None
        operation, value = constraint["op"], constraint["value"]
        if operation == "eq":
            self.forced[name] = {"value": value, "constraint_id": constraint["id"]}
        elif operation == "ne":
            self.banned.setdefault(name, []).append(value)
        elif operation == "in":
            self.allowed[name] = list(value)

    def permits(self, name, value):
        # type: (str, Any) -> bool
        if value in self.banned.get(name, []):
            return False
        return name not in self.allowed or value in self.allowed[name]


def constraint_source(constraint_id):
    # type: (str) -> str
    return "constraint:" + constraint_id


def is_choice(constraint):
    # type: (dict) -> bool
    return constraint["key"] in (MODE_KEY, QUALITY_KEY, MATERIAL_KEY)


def apply_constraints(constraints, plan, params, space, line_width):
    # type: (list, dict, dict, dict, float) -> tuple
    """Constraints on settings (not on the three choices). Return (pass-through {key: constraint}, applied
    records, unsatisfied items)."""
    by_key = _index(params, space)
    passthrough = {}  # type: dict
    applied, unsatisfied = [], []
    for constraint in constraints:
        key = constraint["key"]
        target = by_key.get(key)
        if target is not None and target[0] == "param":
            note = _limit_axis(constraint, params[target[1]], target[2], plan, line_width)
        elif target is not None:
            note = _restrict_discrete(constraint, target[1], plan)
        else:
            note = _pass_through(constraint, passthrough)
        if note is None:
            applied.append({"id": constraint["id"], "result": "applied", "why": constraint["reason"] or key})
        else:
            applied.append({"id": constraint["id"], "result": "not_applied", "why": note})
            unsatisfied.append({"requirement_id": constraint_source(constraint["id"]), "why": note})
    return passthrough, applied, unsatisfied


def _index(params, space):
    """Slicer key -> ("param", id, domain) or ("discrete", id); derived keys map to the axis they come from."""
    index = {}
    for param in params.values():
        index[param.key] = ("param", param.id, "thickness" if param.emit_as else "value")
    index["wall_line_count"] = ("param", "wall_line_count", "lines")
    for item in space["discrete"]:
        keys = [item["key"]] if isinstance(item["key"], str) else []
        if item["id"] == "cool_fan_enabled":
            keys = ["cool_fan_enabled", "cool_fan_enabled_classic", "cool_fan_enabled_cylindrical"]
        for key in keys:
            index[key] = ("discrete", item["id"])
    return index


def _limit_axis(constraint, param, domain, plan, line_width):
    operation, value = constraint["op"], constraint["value"]
    if operation not in ("eq", "min", "max") or isinstance(value, bool) or not isinstance(value, (int, float)):
        return "op %s with value %r is not supported on %s" % (operation, value, constraint["key"])
    if domain == "thickness":
        value = wall_lines(value, line_width)
    minimum = value if operation in ("eq", "min") else None
    maximum = value if operation in ("eq", "max") else None
    limit_param(plan, param, constraint_source(constraint["id"]), minimum, maximum)
    return None


def _restrict_discrete(constraint, discrete_id, plan):
    operation, value = constraint["op"], constraint["value"]
    rule_id = constraint_source(constraint["id"])
    if operation == "eq":
        plan["discrete"][discrete_id] = {"value": value, "rule_id": rule_id}
    elif operation == "ne":
        plan["banned"].setdefault(discrete_id, []).append(value)
        plan["restricted_by"][discrete_id] = rule_id
    elif operation == "in":
        plan["allowed"][discrete_id] = list(value)
        plan["restricted_by"][discrete_id] = rule_id
    else:
        return "op %s is not supported on %s" % (operation, constraint["key"])
    return None


def _pass_through(constraint, passthrough):
    """A key stage 2 does not model: take the demanded value as is (min/max: the bound itself)."""
    operation, value = constraint["op"], constraint["value"]
    if operation == "ne":
        return "stage 2 does not model %s and cannot pick a value other than %r" % (constraint["key"], value)
    passthrough[constraint["key"]] = dict(constraint, value=value[0] if operation == "in" else value)
    return None


def wall_lines(thickness, line_width):
    # type: (float, float) -> int
    """Wall line count the slicer derives from wall_thickness (fdmprinter `wall_line_count` formula)."""
    if thickness == 0:
        return 0
    return max(1, int(round((thickness - line_width) / line_width)) + 1)
