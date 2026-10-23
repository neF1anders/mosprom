"""Rank catalog materials against task-card requirements."""
from tuning.catalog.materials import load_traits

OK, WARN, FAIL, UNKNOWN, NOT_APPLICABLE = "ok", "warn", "fail", "unknown", "na"
_SCORE = {OK: 1.0, WARN: 0.4, UNKNOWN: 0.3, FAIL: 0.0}
_HARD_WEIGHT, _SOFT_WEIGHT = 3.0, 1.0
_POOL_PREFIXES = ("enduse_", "fiberpart_", "sealant_")


def _scale(value, mapping):
    return mapping.get(value, UNKNOWN)


def _threshold(trait):
    """Check that a numeric trait reaches the required value."""
    def check(material, required, flags):
        value = material.traits.get(trait)
        if value is None:
            return UNKNOWN, "no %s data (general knowledge table, not verified)" % trait
        return (OK if value >= float(required) else FAIL), "%s=%s" % (trait, value)
    return check


def _hydrophobic(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    level = material.traits.get("hygroscopic")
    return _scale(level, {"low": OK, "medium": WARN, "high": FAIL}), "hygroscopic=%s" % level


def _uv(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    if flags["uv_bad"]:
        return FAIL, "catalog description says it is not weather resistant"
    if flags["uv_good"]:
        return OK, "catalog description mentions UV resistance"
    level = material.traits.get("uv")
    return _scale(level, {"good": OK, "fair": WARN, "poor": FAIL}), "uv=%s" % level


def _chemicals(material, required, flags):
    stems = load_traits()["chemical_stems"]
    text = material.description.lower()
    matched = [item for item in required if any(stem in text for stem in stems.get(item, [item.lower()]))]
    if len(matched) == len(required):
        return OK, "catalog description mentions: %s" % ", ".join(matched)
    if matched:
        return WARN, "catalog description covers only: %s" % ", ".join(matched)
    return UNKNOWN, "catalog description does not mention the required media"


def _flexible(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    value = material.traits.get("flexible")
    if value is None:
        return UNKNOWN, "no flexibility data"
    return (OK if value else FAIL), "flexible=%s" % value


def _density(material, required, flags):
    if material.density is None:
        return UNKNOWN, "no density in catalog"
    return (OK if material.density <= float(required) else FAIL), "density=%s g/cm3 (catalog)" % material.density


def _friction(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    level = material.traits.get("friction")
    return _scale(level, {"low": OK, "medium": WARN, "high": FAIL}), "friction=%s" % level


def _abrasion(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    level = material.traits.get("abrasion")
    return _scale(level, {"good": OK, "fair": WARN, "poor": FAIL}), "abrasion=%s" % level


def _stiffness(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    level = material.traits.get("stiffness")
    return _scale(level, {"high": OK, "medium": WARN, "low": FAIL}), "stiffness=%s" % level


def _food(material, required, flags):
    if not required:
        return NOT_APPLICABLE, ""
    if flags["food_safe"]:
        return OK, "catalog description declares food contact"
    return UNKNOWN, "food contact not declared in the catalog"


def _unverifiable(material, required, flags):
    return UNKNOWN, "cannot be checked from the catalog"


_CHECKS = {
    "tg_min_c": _threshold("tg_c"),
    "service_temp_max_c": _threshold("service_max_c"),
    "hydrophobic": _hydrophobic,
    "uv_stable": _uv,
    "chemical_resistance": _chemicals,
    "flexible": _flexible,
    "density_max_g_cm3": _density,
    "low_friction": _friction,
    "abrasion_resistant": _abrasion,
    "high_stiffness": _stiffness,
    "food_safe": _food,
    "esd": _unverifiable,
}


def _text_flags(material):
    markers = load_traits()["text_flags"]
    text = material.description.lower()
    return {name: any(marker in text for marker in values) for name, values in markers.items()}


def evaluate(material, requirements):
    # type: (object, list) -> dict
    """Check one material against requirements; returns verdicts per requirement id plus a score."""
    flags = _text_flags(material)
    checks = []
    total_weight = 0.0
    earned = 0.0
    for requirement in requirements:
        check = _CHECKS.get(requirement["key"])
        if check is None:
            continue
        status, detail = check(material, requirement["value"], flags)
        if status == NOT_APPLICABLE:
            continue
        weight = _HARD_WEIGHT if requirement.get("hard") else _SOFT_WEIGHT
        total_weight += weight
        earned += weight * _SCORE[status]
        checks.append({"requirement_id": requirement["id"], "key": requirement["key"], "hard": bool(requirement.get("hard")),
                       "status": status, "detail": detail})
    return {"material": material.id, "checks": checks, "score": earned / total_weight if total_weight else 0.5}


def rank_materials(materials, requirements):
    # type: (dict, list) -> list
    """Evaluate the printable pool, best first; ties broken by material id for determinism."""
    pool = [m for m in materials.values() if m.id.startswith(_POOL_PREFIXES)]
    evaluations = [dict(evaluate(material, requirements), hard_failures=0) for material in pool]
    for evaluation in evaluations:
        evaluation["hard_failures"] = sum(1 for c in evaluation["checks"] if c["hard"] and c["status"] == FAIL)
    return sorted(evaluations, key=lambda e: (e["hard_failures"], -e["score"], e["material"]))
