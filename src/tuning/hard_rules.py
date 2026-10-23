"""Independent check of the hard rules (spec 4.2) on a finished param_set."""

import math
from typing import Any  # noqa: F401  (used in type comments)


def _values(param_set):
    return {setting["key"]: setting["value"] for setting in param_set["settings"]}


def hard_rule_violations(param_set, profile, material):
    # type: (dict, dict, Any) -> list
    """Return human-readable violations; an empty list means the set respects the hard rules."""
    values = _values(param_set)
    found = []
    for key in ("classic_layer_height", "cylindrical_layer_height"):
        if key in values and values[key] > 0.8 * profile["nozzle_mm"] + 1e-9:
            found.append("%s=%s exceeds 0.8 * nozzle" % (key, values[key]))
    if values.get("wall_line_count", 2) < 2:
        found.append("wall_line_count < 2")
    for key in ("top_layers", "bottom_layers"):
        if key in values and values[key] < 3:
            found.append("%s < 3" % key)
    temperature = values.get("material_print_temperature")
    if temperature is not None:
        if temperature > profile["temperature_max_c"]:
            found.append("nozzle temperature above machine limit")
        nominal = material.print_temperature
        if nominal is not None and not (nominal - 10 - 1e-9 <= temperature <= nominal + 10 + 1e-9):
            found.append("nozzle temperature outside the material window")
    mode = param_set["printing_mode"]["value"]
    if mode not in profile["modes"]:
        found.append("unknown printing mode %s" % mode)
    return found


def fits_build_volume(size, profile, mode):
    # type: (list, dict, str) -> bool
    volume = profile["build_volume_mm"]
    limits = [volume["width"], volume["depth"], volume["height"][mode]]
    return all(math.floor(extent * 1000) <= math.floor(limit * 1000) for extent, limit in zip(size, limits))
