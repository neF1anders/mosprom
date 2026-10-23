"""Search space: normalised axes t in [0, 1] (0 = cheap/fast/brittle, 1 = costly/slow/strong)."""

import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.serialization import load_json_file

_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROFILE_ID = "hte530v5.2"


def load_profile(profile_id=DEFAULT_PROFILE_ID):
    # type: (str) -> dict
    return load_json_file(os.path.join(_DIRECTORY, "profile.%s.json" % profile_id))


def load_search_space():
    # type: () -> dict
    return load_json_file(os.path.join(_DIRECTORY, "search_space.json"))


def lookup(context, dotted):
    # type: (dict, str) -> Any
    node = context
    for part in dotted.split("."):
        node = node[part]
    return node


def resolve_number(spec, context):
    # type: (Any, dict) -> float
    """A literal number or {"ref": "dotted.path", "mul": m, "add": a}."""
    if isinstance(spec, dict):
        value = float(lookup(context, spec["ref"]))
        return value * spec.get("mul", 1.0) + spec.get("add", 0.0)
    return float(spec)


class Param(object):
    """One searchable parameter with a monotone map between t and its value."""

    def __init__(self, definition, context):
        # type: (dict, dict) -> None
        self.id = definition["id"]
        self.unit = definition.get("unit", "")
        self.kind = definition["kind"]
        self.step = float(definition["step"])
        self.keys = definition.get("keys", {})
        self.emit = definition.get("emit")
        self.v0 = resolve_number(definition["v0"], context)
        self.v1 = resolve_number(definition["v1"], context)

    def value_at(self, t):
        # type: (float) -> float
        return self.quantize(self.v0 + t * (self.v1 - self.v0))

    def t_of(self, value):
        # type: (float) -> float
        return (value - self.v0) / (self.v1 - self.v0)

    def quantize(self, value):
        # type: (float) -> float
        low, high = sorted((self.v0, self.v1))
        snapped = round(value / self.step) * self.step
        snapped = min(max(snapped, low), high)
        return int(round(snapped)) if self.kind == "int" else round(snapped, 4)


def t_interval_for_limits(param, minimum, maximum):
    # type: (Param, Any, Any) -> tuple
    """Convert value-domain limits (None = open) to an interval of t."""
    low, high = 0.0, 1.0
    for limit, is_minimum in ((minimum, True), (maximum, False)):
        if limit is None:
            continue
        t_limit = param.t_of(limit)
        # With v1 > v0 a value minimum raises t; with v1 < v0 it lowers t.
        raises_t = is_minimum == (param.v1 > param.v0)
        if raises_t:
            low = max(low, t_limit)
        else:
            high = min(high, t_limit)
    return low, high
