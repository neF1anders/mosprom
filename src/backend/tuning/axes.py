"""Search space: normalised axes t in [0, 1] (0 = cheap/fast/brittle, 1 = costly/slow/strong).

The axes and the discrete settings are data (``search_space.json``); an axis gets its ends
from the printer mode and the material once both are chosen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..domain.models import Value
from .notes import EPSILON

LAYER_AXIS = "layer_height"
# Numbers an axis end or a rule limit may refer to, see AxisContext.
ContextRef = Literal[
    "profile.nozzle_mm",
    "profile.defaults.speed_print",
    "material.print_temperature",
    "material.speed",
    "material.speed_floor",
    "material.infill_min_pct",
    "limits.temperature_max_c",
]


class NumberRef(Value):
    """``value(ref) * mul + add``."""

    ref: ContextRef
    mul: float = 1.0
    add: float = 0.0


NumberSpec = float | NumberRef


class QualityLayer(Value):
    """The layer of the chosen quality profile."""

    quality_layer: Literal[True]


class SettingBaseline(Value):
    """The value of a setting: the quality profile's, else the printer's."""

    setting: str
    as_lines: Literal["wall_lines"] | None = Field(default=None, alias="as")


class MaterialBaseline(Value):
    """The print temperature of the material file."""

    material: Literal["print_temperature"]


class AxisSpec(Value):
    id: str
    key: str
    unit: str = ""
    kind: Literal["float", "int"]
    step: float
    v0: NumberSpec
    v1: NumberSpec
    baseline: QualityLayer | SettingBaseline | MaterialBaseline
    emit_as: Literal["wall_thickness_from_lines"] | None = None
    scope: str | None = None


class DiscreteSpec(Value):
    id: str
    key: str
    # The key to send in each printing mode when the slicer does not link it to ``key``.
    mode_keys: dict[str, str] = Field(default_factory=dict)
    candidates: list[bool | str]
    scope: str | None = None

    def sent_key(self, mode: str) -> str:
        return self.mode_keys.get(mode, self.key)

    def constrained_keys(self) -> list[str]:
        """Keys a check constraint may name for this setting."""
        return list(dict.fromkeys([self.key, *self.mode_keys.values()]))


class SearchSpace(Value):
    note: str
    params: list[AxisSpec]
    discrete: list[DiscreteSpec]


SPACE = SearchSpace.model_validate_json(
    Path(__file__).with_name("search_space.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class AxisContext:
    """Numbers of the chosen printer mode and material that axis ends and rule limits use."""

    nozzle: float
    default_speed: float
    material_temperature: float
    material_speed: float | None
    speed_floor: float
    temperature_max: float
    # The datasheet's least infill for a functional part; rules read it only when it is known.
    infill_min: float | None = None

    def number(self, spec: NumberSpec) -> float:
        if isinstance(spec, NumberRef):
            return float(getattr(self, _CONTEXT_FIELDS[spec.ref])) * spec.mul + spec.add
        return float(spec)


_CONTEXT_FIELDS: dict[ContextRef, str] = {
    "profile.nozzle_mm": "nozzle",
    "profile.defaults.speed_print": "default_speed",
    "material.print_temperature": "material_temperature",
    "material.speed": "material_speed",
    "material.speed_floor": "speed_floor",
    "material.infill_min_pct": "infill_min",
    "limits.temperature_max_c": "temperature_max",
}


@dataclass(frozen=True)
class Axis:
    """One searchable parameter with a monotone map between t and its value."""

    spec: AxisSpec
    v0: float
    v1: float

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def step(self) -> float:
        return self.spec.step

    def value_at(self, t: float, low: float = 0.0, high: float = 1.0) -> float:
        """The step value nearest to t that stays inside the hard interval [low, high] of t.

        A step past a limit gives way to the nearest step inside: a maximum rounds down and a
        minimum up. When no step lies inside, the limit itself is the value; an empty interval
        has no such value, its middle t is snapped as it is.
        """
        raw = self.v0 + t * (self.v1 - self.v0)
        if low > high + EPSILON:
            return self._snapped(raw)
        bottom, top = sorted(self.v0 + bound * (self.v1 - self.v0) for bound in (low, high))
        snapped = round(raw / self.step) * self.step
        if snapped > top + EPSILON:
            snapped = math.floor(round(top / self.step, 6)) * self.step
        if snapped < bottom - EPSILON:
            snapped = math.ceil(round(bottom / self.step, 6)) * self.step
        if not bottom - EPSILON <= snapped <= top + EPSILON:
            snapped = min(max(raw, bottom), top)
        return self._typed(snapped)

    def t_of(self, value: float) -> float:
        return (value - self.v0) / (self.v1 - self.v0)

    def reachable(self, limit: float, is_minimum: bool) -> float:
        """The limit an integer axis can meet: a minimum rounds up to a step, a maximum down."""
        if self.spec.kind != "int":
            return limit
        steps = round(limit / self.step, 6)
        return (math.ceil(steps) if is_minimum else math.floor(steps)) * self.step

    def clamped_t_of(self, value: float) -> float:
        return min(max(self.t_of(value), 0.0), 1.0)

    def _snapped(self, value: float) -> float:
        """Snap to the step inside the axis; an integer axis gives an ``int``."""
        low, high = sorted((self.v0, self.v1))
        snapped = round(value / self.step) * self.step
        return self._typed(min(max(snapped, low), high))

    def _typed(self, value: float) -> float:
        if self.spec.kind == "int":
            return int(round(value))
        return round(value, 4)


def build_axes(context: AxisContext) -> dict[str, Axis]:
    return {
        spec.id: Axis(spec, context.number(spec.v0), context.number(spec.v1))
        for spec in SPACE.params
    }


def t_interval_for_limits(
    axis: Axis, minimum: float | None, maximum: float | None
) -> tuple[float, float]:
    """Value limits (None = open) as an interval of t."""
    low, high = 0.0, 1.0
    for limit, is_minimum in ((minimum, True), (maximum, False)):
        if limit is None:
            continue
        t_limit = axis.t_of(axis.reachable(limit, is_minimum))
        # With v1 > v0 a value minimum raises t; with v1 < v0 it lowers t.
        if is_minimum == (axis.v1 > axis.v0):
            low = max(low, t_limit)
        else:
            high = min(high, t_limit)
    return low, high
