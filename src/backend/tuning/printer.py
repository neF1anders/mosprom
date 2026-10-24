"""The printer as parameter selection sees it, read from the catalog of the issued build.

Values follow the slicer: a value chosen by selection or set by the quality profile, else the
extruder's, else the printer's (override formulas are resolved by the catalog), else the
``fdmprinter`` formula or default. Only the preferred quality profile is not in the catalog;
it comes from ``printer.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..domain.catalog import PRINTING_MODES, Catalog
from ..domain.errors import AppError
from ..domain.formulas import evaluate
from ..domain.models import Value

EXTRUDER = "0"
BASE_DIAMETER_KEY = "cylindrical_mode_base_diameter"
_NOTHING: Mapping[str, Any] = MappingProxyType({})


class _PrinterData(Value):
    note: str
    default_quality: str


_DATA = _PrinterData.model_validate_json(
    Path(__file__).with_name("printer.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class QualityOption:
    """A quality profile: its layer and the plain numbers it sets."""

    name: str
    label: str
    layer_height: float
    values: Mapping[str, float]


@dataclass(frozen=True)
class Mode:
    """A printing mode of the printer: its print area and the values the slicer uses in it."""

    name: str
    label: str
    width: float
    depth: float
    height: float
    elliptic: bool
    # X range of the table outside the disallowed strips.
    usable_x: tuple[float, float]
    heated_bed: bool
    line_width: float
    temperature_max: float
    # Diameter of the cylinder the slicer prints around in 5D; None where it does not apply.
    base_diameter: float | None
    # The narrowest such cylinder the build accepts (its ``minimum_value``).
    base_diameter_min: float
    qualities: Mapping[str, QualityOption]
    catalog: Catalog = field(repr=False, compare=False)

    def value(
        self, key: str, quality: QualityOption | None = None, chosen: Mapping[str, Any] = _NOTHING
    ) -> Any:
        """The value the slicer uses for ``key`` with ``chosen`` and the quality profile."""
        above = {**(quality.values if quality else {}), **chosen}
        return slicer_value(self.catalog, self.name, key, above)


@dataclass(frozen=True)
class Printer:
    id: str
    nozzle: float
    filament: float
    default_quality: str
    modes: Mapping[str, Mode]


def load_printer(catalog: Catalog) -> Printer:
    extruder = catalog.extruder_overrides.get(EXTRUDER, {})
    filament = catalog.filament_diameter(EXTRUDER)
    if filament is None or "machine_nozzle_size" not in extruder:
        raise AppError("В каталоге сборки нет сопла или прутка экструдера", "catalog_extruder")
    if _DATA.default_quality not in catalog.qualities:
        raise AppError("В каталоге сборки нет профиля качества по умолчанию", "catalog_quality")
    return Printer(
        id=catalog.printer,
        nozzle=float(extruder["machine_nozzle_size"]),
        filament=float(filament),
        default_quality=_DATA.default_quality,
        modes=MappingProxyType({name: _mode(catalog, name) for name in PRINTING_MODES}),
    )


def slicer_value(catalog: Catalog, mode: str, key: str, above: Mapping[str, Any]) -> Any:
    """The slicer's value of ``key`` in ``mode``; ``above`` holds values set over the printer."""
    if key in above:
        return above[key]
    extruder = catalog.extruder_overrides.get(EXTRUDER, {})
    if key in extruder:
        return extruder[key]
    formula = catalog.settings.get(key, {}).get("value")
    if key in catalog.printer_overrides or not isinstance(formula, str):
        return catalog.values(mode).get(key)
    return evaluate(formula, partial(slicer_value, catalog, mode, above=above))


def _mode(catalog: Catalog, name: str) -> Mode:
    value = partial(slicer_value, catalog, name, above=_NOTHING)
    width = float(value("machine_width"))
    warning = catalog.definition("material_print_temperature")["maximum_value_warning"]
    base = catalog.definition(BASE_DIAMETER_KEY)
    return Mode(
        name=name,
        label=catalog.definition("printing_mode")["options"][name],
        width=width,
        depth=float(value("machine_depth")),
        height=float(value("machine_height")),
        elliptic=value("machine_shape") == "elliptic",
        usable_x=_usable_x(width, value("machine_disallowed_areas")),
        heated_bed=bool(value("machine_heated_bed")),
        line_width=float(value("line_width")),
        temperature_max=float(evaluate(str(warning), value)),
        base_diameter=_base_diameter(catalog, name),
        base_diameter_min=float(evaluate(str(base.get("minimum_value", 0)), value)),
        qualities=MappingProxyType(_qualities(catalog, name)),
        catalog=catalog,
    )


def _usable_x(width: float, disallowed: list[list[list[float]]]) -> tuple[float, float]:
    """A strip left of the centre raises the left edge, one right of it lowers the right edge."""
    low, high = -width / 2.0, width / 2.0
    for area in disallowed:
        xs = [point[0] for point in area]
        if max(xs) <= 0:
            low = max(low, max(xs))
        elif min(xs) >= 0:
            high = min(high, min(xs))
    return low, high


def _base_diameter(catalog: Catalog, mode: str) -> float | None:
    lookup = partial(slicer_value, catalog, mode, above=_NOTHING)
    enabled = catalog.definition(BASE_DIAMETER_KEY).get("enabled", True)
    if isinstance(enabled, str) and not evaluate(enabled, lookup):
        return None
    return lookup(BASE_DIAMETER_KEY)


def _qualities(catalog: Catalog, mode: str) -> dict[str, QualityOption]:
    """Profiles without a layer print with the printer's layer height."""
    default_layer = float(slicer_value(catalog, mode, "layer_height", _NOTHING))
    options = {}
    for name, profile in catalog.qualities.items():
        values = _numbers(profile.values)
        layer = values.get("layer_height", default_layer)
        options[name] = QualityOption(name, profile.name, layer, MappingProxyType(values))
    return options


def _numbers(values: Mapping[str, str]) -> dict[str, float]:
    found = {}
    for key, text in values.items():
        try:
            found[key] = float(text)
        except ValueError:
            continue  # a formula such as "=math.ceil(speed_print * 40 / 60)"
    return found
