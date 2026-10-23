"""Flat fact dictionary that rule conditions are evaluated against."""

_GEOMETRY_FACTS = ("overhang_area_fraction", "needs_repair", "min_wall_estimate_mm", "volume_mm3", "surface_area_mm2")


def build_facts(card, geometry):
    # type: (dict, dict) -> dict
    facts = {}
    preferences = card.get("preferences", {})
    priority = preferences.get("priority") or []
    if priority:
        facts["pref.priority_first"] = priority[0]
    facts["pref.supports_allowed"] = preferences.get("supports_allowed", True)
    facts["pref.quantity"] = preferences.get("quantity", 1)
    if preferences.get("printing_mode"):
        facts["pref.printing_mode"] = preferences["printing_mode"]
    if card.get("part", {}).get("load"):
        facts["part.load"] = card["part"]["load"]
    for requirement in card.get("requirements", []):
        key = requirement["key"]
        facts["req." + key] = requirement["value"]
        facts["reqhard." + key] = facts.get("reqhard." + key, False) or requirement["hard"]
    for name in _GEOMETRY_FACTS:
        if name in geometry:
            facts["geometry." + name] = geometry[name]
    return facts
