from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .formulas import FormulaError, evaluate

PRINTING_MODES = ("classic", "cylindrical", "cylindrical_full")
# названия режимов печати
MODE_NAMES = {"classic": "3D", "cylindrical": "5D Spiral", "cylindrical_full": "5D"}
# экструдер набора параметров
EXTRUDER = "0"
# ключи значения переопределения
_VALUE_KEYS = ("value", "default_value")


@dataclass(frozen=True)
class MaterialProfile:
    id: str
    brand: str
    label: str
    description: str
    density: float | None
    diameter: float | None
    print_temperature: float | None
    bed_temperature: float | None
    speed: float | None
    cooling_percent: float | None


@dataclass(frozen=True)
class QualityProfile:
    quality_type: str
    name: str
    values: Mapping[str, str]

    def numbers(self) -> dict[str, float]:
        """Числа, заданные профилем."""
        found = {}
        for key, text in self.values.items():
            try:
                found[key] = float(text)
            except ValueError:
                continue
        return found


@dataclass(frozen=True)
class Catalog:
    printer: str
    digest: str
    settings: Mapping[str, Mapping[str, Any]]
    printer_overrides: Mapping[str, Mapping[str, Any]]
    extruder_overrides: Mapping[str, Mapping[str, Any]]
    qualities: Mapping[str, QualityProfile]
    materials: Mapping[str, MaterialProfile]

    def definition(self, key: str) -> dict[str, Any]:
        """Определение настройки с ограничениями."""
        merged = dict(self.settings.get(key, {}))
        overrides = self.printer_overrides.get(key, {})
        merged.update({k: v for k, v in overrides.items() if k not in _VALUE_KEYS})
        return merged

    def values(self, mode: str, above: Mapping[str, Any] = MappingProxyType({})) -> ModeValues:
        return ModeValues(self, mode, above)

    def filament_diameter(self, position: str) -> float | None:
        return self.extruder_overrides.get(position, {}).get("material_diameter")


@dataclass
class ModeValues:
    """Значения слайсера для режима."""

    catalog: Catalog
    mode: str
    above: Mapping[str, Any] = field(default_factory=dict)
    _cache: dict[str, Any] = field(default_factory=dict)
    _resolving: set[str] = field(default_factory=set)

    def get(self, key: str) -> Any:
        if key == "printing_mode":
            return self.mode
        if key not in self._cache:
            self._cache[key] = self._resolve(key)
        return self._cache[key]

    def _resolve(self, key: str) -> Any:
        if key in self._resolving:
            raise FormulaError(f"формула ссылается сама на себя: {key}")
        self._resolving.add(key)
        try:
            return self._value(key)
        finally:
            self._resolving.discard(key)

    def _value(self, key: str) -> Any:
        if key in self.above:
            return self.above[key]
        extruder = self.catalog.extruder_overrides.get(EXTRUDER, {})
        if key in extruder:
            return extruder[key]
        for source in (
            self.catalog.printer_overrides.get(key, {}),
            self.catalog.settings.get(key, {}),
        ):
            formula = source.get("value")
            if isinstance(formula, str):
                return evaluate(formula, self.get)
            if "value" in source:
                return formula
            if "default_value" in source:
                return source["default_value"]
        return None
