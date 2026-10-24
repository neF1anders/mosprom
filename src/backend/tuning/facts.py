"""Flat facts that rule conditions are evaluated against.

A measure the STL report does not give is not a fact, so the rules that read it do not fire:
without ``overhangs`` in the report that is ``geometry.overhang_area_fraction`` of the support
and 5D rules.
"""

from __future__ import annotations

from .intake import TuningInput
from .materials import Candidate
from .rules import FactValue

MODE_FACT = "print.mode"
OVERHANG_FACT = "geometry.overhang_area_fraction"


def build_facts(request: TuningInput, material: Candidate) -> dict[str, FactValue]:
    facts: dict[str, FactValue] = {}
    if request.priority:
        facts["pref.priority_first"] = request.priority[0]
    facts["pref.supports_allowed"] = request.supports_allowed
    facts["pref.quantity"] = request.quantity
    if request.mode is not None:
        facts["pref.printing_mode"] = request.mode.mode
    if request.load is not None:
        facts["part.load"] = request.load
    for requirement in request.requirements:
        facts[f"req.{requirement.key}"] = requirement.value
        hard = facts.get(f"reqhard.{requirement.key}", False)
        facts[f"reqhard.{requirement.key}"] = bool(hard) or requirement.hard
    geometry = request.geometry
    facts["geometry.is_revolution"] = geometry.revolution
    facts["geometry.bore_through"] = geometry.bore_through
    facts["geometry.slenderness"] = round(geometry.slenderness, 3)
    measures = {
        OVERHANG_FACT: geometry.overhang_fraction,
        "geometry.length_to_diameter": geometry.length_to_diameter,
        "material.speed": material.speed,
        "material.cooling_pct": material.cooling_percent,
        "material.warp": material.traits.warp,
    }
    facts.update({name: value for name, value in measures.items() if value is not None})
    return facts


def with_mode(
    facts: dict[str, FactValue], mode: str, overhang_fraction: float | None
) -> dict[str, FactValue]:
    """The facts once the mode is chosen: the mode, and the overhangs of the pose it prints in."""
    found = {key: value for key, value in facts.items() if key != OVERHANG_FACT}
    found[MODE_FACT] = mode
    if overhang_fraction is not None:
        found[OVERHANG_FACT] = overhang_fraction
    return found
