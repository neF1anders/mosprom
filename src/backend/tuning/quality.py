"""Quality profile and layer: the printer's default profile with the layer the rules ask for.

Stereotech technologists save their projects with the default profile and the layer set on
top of it (``quality_type = normal``, ``layer_height = 0.2``), so the profile stays the default
and the layer is sent as a number when it differs from the profile's. The target layer snaps to
the layers of the build's profiles inside the hard limits, so it is always a value the slicer
offers; a check constraint on the profile chooses the profile instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from .axes import Axis
from .constraints import QUALITY_KEY, Choices
from .notes import EPSILON, SettingChoice
from .planning import AxisPlan, Plan, resolve_t
from .printer import Mode, QualityOption
from .rules import reason, source_of


@dataclass(frozen=True)
class QualityChoice:
    profile: QualityOption
    why: str
    source: str
    # The layer the print uses, and the explicit layer setting when the profile's differs.
    layer_height: float
    layer_setting: SettingChoice | None = None


def choose_quality(
    plan: Plan, axis: Axis, mode: Mode, choices: Choices, default: str
) -> QualityChoice:
    qualities = mode.qualities
    forced = choices.forced.get(QUALITY_KEY)
    if forced is not None and forced.value in qualities:
        profile = qualities[forced.value]
        source = f"constraint:{forced.constraint_id}"
        return QualityChoice(
            profile, "профиль задан ограничением этапа 3", source, profile.layer_height
        )
    entry = plan.axes[axis.id]
    t, rule_id = resolve_t(entry, axis.clamped_t_of(qualities[default].layer_height))
    layer = _layer(entry, axis, t, mode)
    permitted = [name for name in sorted(qualities) if choices.permits(QUALITY_KEY, name)]
    if default in permitted or not permitted:
        profile = qualities[default]
        why = f"профиль принтера по умолчанию: {profile.label}"
        source = "default"
    else:
        name = min(permitted, key=lambda option: abs(qualities[option].layer_height - layer))
        profile = qualities[name]
        why = f"профиль {qualities[default].label} исключён этапом 3, ближайший — {profile.label}"
        source = source_of(rule_id)
    if abs(layer - profile.layer_height) < EPSILON:
        return QualityChoice(profile, f"{why}, слой {layer:g} мм", source, layer)
    setting = SettingChoice(layer, reason(rule_id), source_of(rule_id), "mm")
    why = f"{why}, слой {layer:g} мм задан отдельно: {reason(rule_id)}"
    return QualityChoice(profile, why, source, layer, setting)


def _layer(entry: AxisPlan, axis: Axis, t: float, mode: Mode) -> float:
    """The profile layer nearest to the target inside the limits, else the target itself."""
    target = axis.v0 + t * (axis.v1 - axis.v0)
    offered = sorted({option.layer_height for option in mode.qualities.values()})
    inside = [
        layer
        for layer in offered
        if entry.low - EPSILON <= axis.t_of(layer) <= entry.high + EPSILON
    ]
    if not inside:
        return axis.value_at(t, entry.low, entry.high)
    return min(inside, key=lambda layer: (abs(layer - target), layer))
