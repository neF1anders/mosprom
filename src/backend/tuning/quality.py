"""Quality profile: the rules give a target layer, it snaps to the nearest profile whose layer
is inside the hard limits. The layer is sent as a number only when no profile fits."""

from __future__ import annotations

from dataclasses import dataclass

from .axes import Axis
from .constraints import QUALITY_KEY, Choices
from .notes import EPSILON, SettingChoice
from .planning import Plan, resolve_t
from .printer import Mode, QualityOption
from .rules import reason, source_of


@dataclass(frozen=True)
class QualityChoice:
    profile: QualityOption
    why: str
    source: str
    # The layer the print uses, and the explicit layer setting when no profile fits.
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
    target = axis.v0 + t * (axis.v1 - axis.v0)
    permitted = [name for name in sorted(qualities) if choices.permits(QUALITY_KEY, name)]
    inside = [
        name
        for name in permitted
        if entry.low - EPSILON <= axis.t_of(qualities[name].layer_height) <= entry.high + EPSILON
    ]
    pool = inside or permitted or sorted(qualities)
    name = min(
        pool,
        key=lambda option: (
            abs(qualities[option].layer_height - target),
            qualities[option].layer_height,
        ),
    )
    profile = qualities[name]
    if not inside:
        layer = axis.quantize(target)
        why = f"ни один профиль не укладывается в ограничения: {reason(rule_id)}"
        setting = SettingChoice(layer, why, source_of(rule_id), "mm")
        return _nearest(profile, rule_id, layer, setting)
    if name == default:
        return _default(profile, rule_id)
    return _nearest(profile, rule_id, profile.layer_height, None)


def _default(profile: QualityOption, rule_id: str | None) -> QualityChoice:
    why = f"профиль по умолчанию принтера: {profile.label}, слой {profile.layer_height:g} мм"
    if rule_id is not None:
        why += (
            f"; правило «{reason(rule_id)}» профиль не изменило: слой упёрся в допустимые пределы"
        )
    return QualityChoice(profile, why, "default", profile.layer_height)


def _nearest(
    profile: QualityOption, rule_id: str | None, layer: float, setting: SettingChoice | None
) -> QualityChoice:
    why = (
        f"{reason(rule_id)}; ближайший профиль — {profile.label}, слой {profile.layer_height:g} мм"
    )
    return QualityChoice(profile, why, source_of(rule_id), layer, setting)
