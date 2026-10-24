"""The issued STE Slicer build as data: settings, printer and extruder overrides, quality
profiles and materials. Parameter selection and its check read the same catalog.

Values are resolved per printing mode the way the slicer does for the printer: an override
formula is evaluated, otherwise its default, otherwise the ``fdmprinter`` default. Formulas of
``fdmprinter`` itself are not evaluated, their defaults stand in for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .formulas import FormulaError, evaluate

PRINTING_MODES = ("classic", "cylindrical", "cylindrical_full")
# Keys of an override that change a setting's value rather than its limits or conditions.
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
        """A setting's definition with the printer's limits, options and conditions."""
        merged = dict(self.settings.get(key, {}))
        overrides = self.printer_overrides.get(key, {})
        merged.update({k: v for k, v in overrides.items() if k not in _VALUE_KEYS})
        return merged

    def values(self, mode: str) -> ModeValues:
        return ModeValues(self, mode)

    def filament_diameter(self, position: str) -> float | None:
        return self.extruder_overrides.get(position, {}).get("material_diameter")


@dataclass
class ModeValues:
    """Printer values in one printing mode, resolved on demand and cached."""

    catalog: Catalog
    mode: str
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
        override = self.catalog.printer_overrides.get(key, {})
        formula = override.get("value")
        if isinstance(formula, str):
            return evaluate(formula, self.get)
        if "value" in override:
            return formula
        if "default_value" in override:
            return override["default_value"]
        return self.catalog.settings.get(key, {}).get("default_value")
