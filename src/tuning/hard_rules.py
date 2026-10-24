"""Independent check of the hard rules (spec 4.2) on a finished stage2.parameter_set."""

import math
from typing import Any  # noqa: F401  (used in type comments)

from tuning.constraints import wall_lines

_TOLERANCE = 1e-9


def _value(parameter_set, key, default):
    setting = (parameter_set.get("settings") or {}).get(key)
    return setting["value"] if setting else default


def hard_rule_violations(parameter_set, profile, material):
    # type: (dict, dict, Any) -> list
    """Human-readable violations; an empty list means the set respects the hard rules."""
    found = []
    mode = parameter_set["printing_mode"]["value"]
    if mode not in profile["modes"]:
        return ["unknown printing mode %s" % mode]
    quality = profile["qualities"].get(parameter_set["quality"]["quality_type"])
    if quality is None:
        return ["unknown quality profile %s" % parameter_set["quality"]["quality_type"]]
    layer = _value(parameter_set, "layer_height", quality["layer_height"])
    if layer > 0.8 * profile["nozzle_mm"] + _TOLERANCE:
        found.append("layer %s mm exceeds 0.8 * nozzle" % layer)
    wall = _value(
        parameter_set, "wall_thickness", quality["values"].get("wall_thickness", profile["defaults"]["wall_thickness"])
    )
    if wall_lines(wall, profile["line_width_mm"]) < 2:
        found.append("fewer than two walls")
    skin = _value(parameter_set, "top_bottom_thickness", profile["defaults"]["top_bottom_thickness"])
    if math.ceil(round(skin / layer, 4)) < 3:
        found.append("fewer than three top/bottom layers")
    temperature = _value(parameter_set, "material_print_temperature", material.print_temperature)
    ceiling = max(profile["temperature_max_c"], material.print_temperature)
    if temperature > ceiling + _TOLERANCE:
        found.append("nozzle temperature above the machine limit")
    if abs(temperature - material.print_temperature) > 10 + _TOLERANCE:
        found.append("nozzle temperature outside the material window")
    if not profile["modes"][mode]["heated_bed"] and "material_bed_temperature" in (parameter_set.get("settings") or {}):
        found.append("bed temperature sent in a mode without a heated bed")
    if material.diameter is not None and abs(material.diameter - profile["filament_mm"]) > _TOLERANCE:
        found.append("material filament does not fit the extruder")
    return found
