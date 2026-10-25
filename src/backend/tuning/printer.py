from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..domain.catalog import EXTRUDER, PRINTING_MODES, Catalog
from ..domain.errors import AppError
from ..domain.formulas import evaluate
from ..domain.models import Value

BASE_DIAMETER_KEY = "cylindrical_mode_base_diameter"
_NOTHING: Mapping[str, Any] = MappingProxyType({})


class _PrinterData(Value):
    note: str
    default_quality: str
    preferred_material: str


_DATA = _PrinterData.model_validate_json(
    Path(__file__).with_name("printer.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class QualityOption:
    """Профиль качества и его числа."""

    name: str
    label: str
    layer_height: float
    values: Mapping[str, float]


@dataclass(frozen=True)
class Mode:
    """Режим печати и его значения."""

    name: str
    label: str
    width: float
    depth: float
    height: float
    elliptic: bool
    # диапазон по X
    usable_x: tuple[float, float]
    heated_bed: bool
    line_width: float
    temperature_max: float
    # диаметр цилиндра 5D
    base_diameter: float | None
    # минимальный такой цилиндр
    base_diameter_min: float
    qualities: Mapping[str, QualityOption]
    catalog: Catalog = field(repr=False, compare=False)

    def value(
        self, key: str, quality: QualityOption | None = None, chosen: Mapping[str, Any] = _NOTHING
    ) -> Any:
        """Значение ключа для слайсера."""
        above = {**(quality.values if quality else {}), **chosen}
        return self.catalog.values(self.name, above).get(key)


@dataclass(frozen=True)
class Printer:
    id: str
    nozzle: float
    filament: float
    default_quality: str
    # базовое имя материала
    preferred_material: str
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
        preferred_material=_DATA.preferred_material,
        modes=MappingProxyType({name: _mode(catalog, name) for name in PRINTING_MODES}),
    )


def _mode(catalog: Catalog, name: str) -> Mode:
    value = catalog.values(name).get
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
    """Полоса стола без запретных зон."""
    low, high = -width / 2.0, width / 2.0
    for area in disallowed:
        xs = [point[0] for point in area]
        if max(xs) <= 0:
            low = max(low, max(xs))
        elif min(xs) >= 0:
            high = min(high, min(xs))
    return low, high


def _base_diameter(catalog: Catalog, mode: str) -> float | None:
    lookup = catalog.values(mode).get
    enabled = catalog.definition(BASE_DIAMETER_KEY).get("enabled", True)
    if isinstance(enabled, str) and not evaluate(enabled, lookup):
        return None
    return lookup(BASE_DIAMETER_KEY)


def _qualities(catalog: Catalog, mode: str) -> dict[str, QualityOption]:
    """Профили без слоя берут высоту."""
    default_layer = float(catalog.values(mode).get("layer_height"))
    options = {}
    for name, profile in catalog.qualities.items():
        values = profile.numbers()
        layer = values.get("layer_height", default_layer)
        options[name] = QualityOption(name, profile.name, layer, MappingProxyType(values))
    return options
