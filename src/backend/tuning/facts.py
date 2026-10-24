"""Flat facts that rule conditions are evaluated against.

A measure the STL report does not give is not a fact, so the rules that read it do not fire:
without ``overhangs`` in the report that is ``geometry.overhang_area_fraction`` of the support
and 5D rules.
"""

from __future__ import annotations

from .intake import TuningInput
from .materials import Candidate
from .rules import FactValue


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
    measures = {
        "geometry.needs_repair": geometry.needs_repair,
        "geometry.min_wall_estimate_mm": geometry.min_wall_estimate,
        "geometry.volume_mm3": geometry.volume,
        "geometry.surface_area_mm2": geometry.surface_area,
        "geometry.overhang_area_fraction": geometry.overhang_fraction,
        "material.speed": material.speed,
        "material.cooling_pct": material.cooling_percent,
    }
    facts.update({name: value for name, value in measures.items() if value is not None})
    return facts
