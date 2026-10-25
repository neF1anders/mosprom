from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..domain.models import Value
from .notes import EPSILON

LAYER_AXIS = "layer_height"
# числа границ осей
ContextRef = Literal[
    "profile.nozzle_mm",
    "profile.defaults.speed_print",
    "material.print_temperature",
    "material.speed",
    "material.speed_floor",
    "material.infill_min_pct",
    "limits.temperature_max_c",
    "geometry.wall_lines_fit",
]


class NumberRef(Value):
    """Ссылка на число контекста."""

    ref: ContextRef
    mul: float = 1.0
    add: float = 0.0


NumberSpec = float | NumberRef


class QualityLayer(Value):
    """Слой выбранного профиля качества."""

    quality_layer: Literal[True]


class SettingBaseline(Value):
    """Базовое значение настройки принтера."""

    setting: str
    as_lines: Literal["wall_lines"] | None = Field(default=None, alias="as")


class MaterialBaseline(Value):
    """Температура печати из файла материала."""

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
    # ключи по режимам
    mode_keys: dict[str, str] = Field(default_factory=dict)
    candidates: list[bool | str]
    scope: str | None = None

    def sent_key(self, mode: str) -> str:
        return self.mode_keys.get(mode, self.key)

    def constrained_keys(self) -> list[str]:
        """Ключи, доступные для ограничений."""
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
    """Числа выбранного режима и материала."""

    nozzle: float
    default_speed: float
    material_temperature: float
    material_speed: float | None
    speed_floor: float
    temperature_max: float
    # минимум по паспорту
    infill_min: float | None = None
    # линии сторон
    wall_lines_fit: float | None = None

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
    "geometry.wall_lines_fit": "wall_lines_fit",
    "limits.temperature_max_c": "temperature_max",
}


@dataclass(frozen=True)
class Axis:
    """Параметр поиска с монотонной шкалой."""

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
        """Ближайший шаг внутри жёстких границ."""
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
        """Достижимая граница целочисленной оси."""
        if self.spec.kind != "int":
            return limit
        steps = round(limit / self.step, 6)
        return (math.ceil(steps) if is_minimum else math.floor(steps)) * self.step

    def clamped_t_of(self, value: float) -> float:
        return min(max(self.t_of(value), 0.0), 1.0)

    def _snapped(self, value: float) -> float:
        """Привязка значения к шагу оси."""
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
    """Границы значения в интервал t."""
    low, high = 0.0, 1.0
    for limit, is_minimum in ((minimum, True), (maximum, False)):
        if limit is None:
            continue
        t_limit = axis.t_of(axis.reachable(limit, is_minimum))
        # зависит от наклона
        if is_minimum == (axis.v1 > axis.v0):
            low = max(low, t_limit)
        else:
            high = min(high, t_limit)
    return low, high
