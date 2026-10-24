"""Settings that differ from the slicer.

Every axis starts at the value the slicer would use anyway (quality profile, material file,
definition) and moves only when a rule or a check constraint asks for it; only such differences
become settings. Keys the selection does not model are sent as a constraint demands them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .axes import (
    LAYER_AXIS,
    SPACE,
    Axis,
    DiscreteSpec,
    MaterialBaseline,
    QualityLayer,
    SettingBaseline,
)
from .constraints import PassThrough, wall_lines
from .materials import Candidate
from .notes import EPSILON, SettingChoice, Unmet
from .planning import AxisPlan, Plan, resolve_t
from .printer import Mode
from .quality import QualityChoice
from .rules import reason, source_of


@dataclass(frozen=True)
class SettingsChoice:
    settings: Mapping[str, SettingChoice]
    unmet: tuple[Unmet, ...]


def choose_settings(
    plan: Plan,
    axes: Mapping[str, Axis],
    mode: Mode,
    quality: QualityChoice,
    material: Candidate,
    pass_through: Mapping[str, PassThrough],
) -> SettingsChoice:
    settings: dict[str, SettingChoice] = {}
    if quality.layer_setting is not None:
        settings[axes[LAYER_AXIS].key] = quality.layer_setting
    for axis_id in sorted(axes):
        axis, baseline = axes[axis_id], axes[axis_id].spec.baseline
        if isinstance(baseline, QualityLayer):
            continue  # the layer comes with the quality profile
        found = _axis_setting(plan, axis, baseline, mode, quality, material)
        if found is not None:
            settings[axis.key] = found
    chosen = {key: setting.value for key, setting in settings.items()}
    unmet = []
    for item in SPACE.discrete:
        setting = _discrete_setting(plan, item, mode, quality, chosen)
        if isinstance(setting, Unmet):
            unmet.append(setting)
        elif setting is not None:
            settings[item.sent_key(mode.name)] = setting
    for key, demanded in sorted(pass_through.items()):
        why = f"ограничение этапа 3: {demanded.reason or key}"
        settings[key] = SettingChoice(demanded.value, why, f"constraint:{demanded.constraint_id}")
    return SettingsChoice(settings, tuple(unmet))


def _axis_setting(
    plan: Plan,
    axis: Axis,
    baseline_spec: SettingBaseline | MaterialBaseline,
    mode: Mode,
    quality: QualityChoice,
    material: Candidate,
) -> SettingChoice | None:
    entry = plan.axes[axis.id]
    baseline = _baseline(baseline_spec, mode, quality, material)
    t, rule_id = resolve_t(entry, axis.clamped_t_of(baseline))
    value = axis.value_at(t, entry.low, entry.high)
    value, rule_id = _enough_layers(plan, axis, value, rule_id, quality.layer_height)
    if rule_id is None or abs(value - baseline) < EPSILON:
        return None
    why = "; ".join(reason(rule) for rule in _decisive_rules(entry, rule_id))
    if axis.spec.emit_as == "wall_thickness_from_lines":
        lines = int(value)
        thickness = round(lines * mode.line_width, 4)
        return SettingChoice(thickness, f"{why}; периметров: {lines}", source_of(rule_id), "mm")
    return SettingChoice(value, why, source_of(rule_id), axis.spec.unit or None, axis.spec.scope)


def _baseline(
    spec: SettingBaseline | MaterialBaseline,
    mode: Mode,
    quality: QualityChoice,
    material: Candidate,
) -> float:
    if isinstance(spec, MaterialBaseline):
        return float(material.print_temperature)
    value = float(mode.value(spec.setting, quality.profile))
    if spec.as_lines == "wall_lines":
        return float(wall_lines(value, mode.line_width))
    return value


def _enough_layers(
    plan: Plan, axis: Axis, value: float, rule_id: str | None, layer_height: float
) -> tuple[float, str | None]:
    """A thickness kept at the minimal number of layers, raised to the next step if needed."""
    minimum = plan.min_layers.get(axis.id)
    if minimum is None:
        return value, rule_id
    needed = minimum.layers * layer_height
    if value + EPSILON >= needed:
        return value, rule_id
    return round(math.ceil(round(needed / axis.step, 6)) * axis.step, 4), minimum.rule_id


def _decisive_rules(entry: AxisPlan, rule_id: str) -> list[str]:
    """The rule that set the value first, then the other rules that moved the same axis."""
    return [rule_id, *(rule for rule in entry.moving_rule_ids if rule != rule_id)]


def _discrete_setting(
    plan: Plan,
    item: DiscreteSpec,
    mode: Mode,
    quality: QualityChoice,
    chosen: Mapping[str, Any],
) -> SettingChoice | Unmet | None:
    """The slicer value unless a rule or a constraint picks another one."""
    baseline = mode.value(item.key, quality.profile, chosen)
    picked = plan.discrete.get(item.id)
    value, rule_id = (picked.value, picked.rule_id) if picked else (baseline, None)
    allowed = plan.allowed.get(item.id)
    banned = plan.banned.get(item.id, ())
    if value in banned or (allowed is not None and value not in allowed):
        options = [
            candidate
            for candidate in item.candidates
            if candidate not in banned and (allowed is None or candidate in allowed)
        ]
        if not options:
            return Unmet(f"discrete:{item.id}", "все допустимые значения запрещены")
        value, rule_id = options[0], plan.restricted_by.get(item.id, rule_id)
    if value == baseline:
        return None
    return SettingChoice(value, reason(rule_id), source_of(rule_id), None, item.scope)
