"""The issued STE Slicer build as data: settings, printer and extruder overrides, quality
profiles and materials. Parameter selection and its check read the same catalog and resolve
values through the same ``ModeValues``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .formulas import FormulaError, evaluate

PRINTING_MODES = ("classic", "cylindrical", "cylindrical_full")
# How people call each printing mode.
MODE_NAMES = {"classic": "3D", "cylindrical": "5D Spiral", "cylindrical_full": "5D"}
# The extruder a parameter set prints with; formulas naming another extruder read it too.
EXTRUDER = "0"
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

    def numbers(self) -> dict[str, float]:
        """The plain numbers the profile sets; a formula such as
        ``=math.ceil(speed_print * 40 / 60)`` is left to the slicer."""
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
        """A setting's definition with the printer's limits, options and conditions."""
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
    """The values the slicer uses in one printing mode, resolved on demand and cached.

    ``above`` holds what is set over the printer: a quality profile's values and the chosen
    ones. A key takes the first of its value in ``above``, the extruder's, the printer's
    override (its formula, else its default), the ``fdmprinter`` formula and the ``fdmprinter``
    default, as in the slicer's stack of settings. Formulas read other keys the same way.
    """

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
