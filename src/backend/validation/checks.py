from __future__ import annotations

import json
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..domain.catalog import MODE_NAMES, Catalog, ModeValues
from ..domain.formulas import evaluate
from ..domain.parameters import Issue, ParameterSet, PlacedModel

Level = Literal["error", "warning", "info"]

# вариант общего ключа
_MODE_VARIANTS = {
    "classic": "_classic",
    "cylindrical": "_cylindrical",
    "cylindrical_full": "_cylindrical",
}
# формула не вычисляется
_UNEVALUATED = (ArithmeticError, LookupError, TypeError, ValueError)
_ROTATION_TOLERANCE = 1e-3
_DIAMETER_TOLERANCE = 1e-6


def check_parameters(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    """Все замечания проверки по порядку."""
    return [issue for check in _CHECKS for issue in check(parameter_set, catalog)]


def _check_printer(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    if parameter_set.printer == catalog.printer:
        return []
    message = f"Набор для принтера {parameter_set.printer}, а сборка для {catalog.printer}"
    return [_issue("error", "printer", "wrong_printer", message, bound=catalog.printer)]


def _check_quality(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    quality_type = parameter_set.quality.quality_type
    if quality_type in catalog.qualities:
        return []
    return [
        _issue(
            "error",
            "quality.quality_type",
            "unknown_quality",
            f"Профиля {_text(quality_type)} нет в сборке",
            key="quality_type",
            bound=sorted(catalog.qualities),
        )
    ]


def _check_materials(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    if not parameter_set.materials:
        return [_issue("error", "materials", "no_materials", "Не выбран ни один материал")]
    return [
        issue
        for position, material in parameter_set.materials.items()
        for issue in _check_material(position, material.id, catalog)
    ]


def _check_material(position: str, material_id: str, catalog: Catalog) -> list[Issue]:
    """Материал есть и подходит экструдеру."""
    where = f"materials[{position}]"
    filament = catalog.filament_diameter(position)
    profile = catalog.materials.get(material_id)
    if profile is None:
        fitting = sorted(
            candidate
            for candidate, other in catalog.materials.items()
            if _fits(other.diameter, filament)
        )
        message = f"Материала {_text(material_id)} нет в сборке"
        return [_issue("error", where, "unknown_material", message, key="material", bound=fitting)]
    if _fits(profile.diameter, filament):
        return []
    message = f"Пруток материала {_text(profile.diameter)} мм, а экструдер под {_text(filament)} мм"
    return [_issue("error", where, "wrong_filament", message, key="material", bound=material_id)]


def _fits(diameter: float | None, filament: float | None) -> bool:
    if diameter is None or filament is None:
        return True
    return abs(diameter - filament) <= _DIAMETER_TOLERANCE


@dataclass(frozen=True)
class _Context:
    """Данные для проверок настроек."""

    catalog: Catalog
    mode: str
    sent: Mapping[str, Any]
    values: ModeValues


def _check_settings(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    mode = parameter_set.printing_mode.value
    sent = {key: setting.value for key, setting in parameter_set.settings.items()}
    profile = catalog.qualities.get(parameter_set.quality.quality_type)
    above = {**(profile.numbers() if profile else {}), **sent}
    context = _Context(catalog, mode, sent, catalog.values(mode, above))
    return [issue for key, value in sent.items() for issue in _check_setting(key, value, context)]


def _check_setting(key: str, value: Any, context: _Context) -> list[Issue]:
    definition = context.catalog.definition(key)
    if not definition:
        return [_setting_issue("error", key, "unknown_key", "Такой настройки нет в слайсере")]
    return [
        *_check_type(key, value, definition),
        *_check_limits(key, value, definition, context),
        *_check_applicability(key, definition, context),
        *_check_mode_key(key, context.mode),
        *_check_mode_variant(key, value, context),
    ]


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# тип JSON слайсера
_JSON_TYPES: dict[str, tuple[Callable[[Any], bool], str]] = {
    "bool": (_is_bool, "логическое значение"),
    "int": (_is_integer, "целое число"),
    "float": (_is_number, "число"),
}


def _check_type(key: str, value: Any, definition: Mapping[str, Any]) -> list[Issue]:
    setting_type = definition.get("type")
    if setting_type == "enum":
        return _check_option(key, value, definition)
    if setting_type not in _JSON_TYPES:
        return []
    accepts, name = _JSON_TYPES[setting_type]
    if accepts(value):
        return []
    message = f"Нужно {name}, а задано {_text(value)}"
    return [_setting_issue("error", key, "wrong_type", message, bound=setting_type)]


def _check_option(key: str, value: Any, definition: Mapping[str, Any]) -> list[Issue]:
    options = list(definition.get("options") or {})
    if value in options:
        return []
    message = f"Значения {_text(value)} нет среди вариантов настройки"
    return [_setting_issue("error", key, "not_in_enum", message, bound=options)]


@dataclass(frozen=True)
class _Limit:
    field: str
    kind: str
    level: Level
    crossed: Callable[[float, float], bool]
    words: str


_LIMITS = (
    _Limit("minimum_value", "below_min", "error", operator.lt, "меньше минимума"),
    _Limit("maximum_value", "above_max", "error", operator.gt, "больше максимума"),
    _Limit(
        "minimum_value_warning", "below_recommended", "warning", operator.lt, "ниже рекомендуемого"
    ),
    _Limit(
        "maximum_value_warning", "above_recommended", "warning", operator.gt, "выше рекомендуемого"
    ),
)


def _check_limits(
    key: str, value: Any, definition: Mapping[str, Any], context: _Context
) -> list[Issue]:
    if definition.get("type") not in ("int", "float") or not _is_number(value):
        return []
    issues = []
    for limit in _LIMITS:
        bound = _bound(definition.get(limit.field), context)
        if bound is not None and limit.crossed(value, bound):
            message = f"{_text(value)} {limit.words} {_text(bound)}"
            issues.append(_setting_issue(limit.level, key, limit.kind, message, bound=bound))
    return issues


def _bound(limit: Any, context: _Context) -> float | None:
    """Предел числом или формулой."""
    try:
        return float(limit)
    except (TypeError, ValueError):
        pass
    if not isinstance(limit, str):
        return None
    try:
        bound = evaluate(limit, context.values.get)
    except _UNEVALUATED:
        return None
    return bound if _is_number(bound) else None


def _check_applicability(key: str, definition: Mapping[str, Any], context: _Context) -> list[Issue]:
    """Условие применимости настройки выполняется."""
    condition = definition.get("enabled")
    if not isinstance(condition, str) or condition.strip() in ("", "True"):
        return []
    try:
        active = evaluate(condition, context.values.get)
    except _UNEVALUATED:
        message = "Не удалось проверить, действует ли настройка"
        return [_setting_issue("info", key, "formula_unknown", message, bound=condition)]
    if active:
        return []
    message = f"При этих значениях настройка не действует в режиме {MODE_NAMES[context.mode]}"
    return [_setting_issue("warning", key, "inactive_in_mode", message, bound=condition)]


@dataclass(frozen=True)
class _ModeKey:
    suffix: str
    modes: tuple[str, ...]
    meant_for: str


# ключи отдельных режимов
_MODE_KEYS = (
    _ModeKey("_classic", ("classic", "cylindrical_full"), "режима 3D"),
    _ModeKey("_cylindrical", ("cylindrical", "cylindrical_full"), "режимов 5D"),
)


def _check_mode_key(key: str, mode: str) -> list[Issue]:
    return [
        _setting_issue(
            "warning",
            key,
            "mode_key_mismatch",
            f"Настройка для {mode_key.meant_for}, а выбран режим {MODE_NAMES[mode]}",
            bound=list(mode_key.modes),
        )
        for mode_key in _MODE_KEYS
        if key.endswith(mode_key.suffix) and mode not in mode_key.modes
    ]


def _check_mode_variant(key: str, value: Any, context: _Context) -> list[Issue]:
    """Общий ключ достигает режима формулой."""
    variant = key + _MODE_VARIANTS[context.mode]
    if variant not in context.catalog.settings or variant in context.sent:
        return []
    formula = context.catalog.settings[variant].get("value")
    if isinstance(formula, str) and re.search(rf"\b{re.escape(key)}\b", formula):
        return []
    message = (
        f"В режиме {MODE_NAMES[context.mode]} слайсер читает отдельную настройку, "
        "значение нужно задать в ней"
    )
    return [
        _issue(
            "warning",
            f"settings.{key}",
            "unlinked_mode_key",
            message,
            key=variant,
            bound=value,
        )
    ]


@dataclass(frozen=True)
class _Bed:
    """Стол одного режима печати."""

    mode: str
    width: float
    depth: float
    height: float
    shape: str

    def holds(self, x: float, y: float) -> bool:
        half_width, half_depth = self.width / 2, self.depth / 2
        if abs(x) > half_width or abs(y) > half_depth:
            return False
        return self.shape != "elliptic" or (x / half_width) ** 2 + (y / half_depth) ** 2 <= 1


def _check_models(parameter_set: ParameterSet, catalog: Catalog) -> list[Issue]:
    if not parameter_set.models:
        return [_issue("error", "models", "no_models", "Нет ни одной модели")]
    mode = parameter_set.printing_mode.value
    printer = catalog.values(mode)
    bed = _Bed(
        mode,
        printer.get("machine_width"),
        printer.get("machine_depth"),
        printer.get("machine_height"),
        printer.get("machine_shape"),
    )
    return [
        issue
        for index, model in enumerate(parameter_set.models)
        for issue in _check_model(f"models[{index}]", model, bed)
    ]


def _check_model(where: str, model: PlacedModel, bed: _Bed) -> list[Issue]:
    return [
        *_check_rotation(where, model),
        *_check_scale(where, model.transform.scale),
        *_check_position(where, model.transform.position, bed),
    ]


def _check_rotation(where: str, model: PlacedModel) -> list[Issue]:
    problem = _rotation_problem(model.transform.rotation)
    if problem is None:
        return []
    return [_issue("error", where, "bad_rotation", problem, bound=model.orientation_candidate)]


def _rotation_problem(matrix: list[list[float]]) -> str | None:
    """Почему матрица не поворот."""
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        return "Поворот задан не матрицей 3 на 3"
    orthonormal = all(
        abs(_dot(matrix[a], matrix[b]) - (a == b)) <= _ROTATION_TOLERANCE
        for a in range(3)
        for b in range(3)
    )
    if orthonormal and abs(_determinant(matrix) - 1) <= _ROTATION_TOLERANCE:
        return None
    return "Матрица не задаёт поворот, она должна быть ортонормированной с определителем 1"


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _determinant(matrix: list[list[float]]) -> float:
    (a, b, c), (d, e, f), (g, h, i) = matrix
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _check_scale(where: str, scale: list[float]) -> list[Issue]:
    if len(scale) == 3 and all(factor > 0 for factor in scale):
        return []
    return [_issue("error", where, "bad_scale", "Масштаб должен быть тремя положительными числами")]


def _check_position(where: str, position: list[float], bed: _Bed) -> list[Issue]:
    """Центр модели над столом."""
    if len(position) != 3:
        return [_issue("error", where, "bad_position", "Положение должно быть тремя числами")]
    x, y, z = position
    issues = []
    if not bed.holds(x, y):
        message = f"Центр модели вне стола режима {MODE_NAMES[bed.mode]}"
        plate = {"width": bed.width, "depth": bed.depth, "shape": bed.shape}
        issues.append(_issue("error", where, "outside_bed", message, bound=plate))
    if not 0 <= z <= bed.height:
        message = f"Высота центра модели вне рабочей области от 0 до {_text(bed.height)} мм"
        issues.append(_issue("error", where, "height_out_of_range", message, bound=[0, bed.height]))
    return issues


def _issue(
    level: Level, where: str, kind: str, message: str, key: str | None = None, bound: Any = None
) -> Issue:
    return Issue(level=level, where=where, kind=kind, message=message, key=key, bound=bound)


def _setting_issue(level: Level, key: str, kind: str, message: str, bound: Any = None) -> Issue:
    return _issue(level, f"settings.{key}", kind, message, key=key, bound=bound)


def _text(value: Any) -> str:
    """Значение в читаемом виде."""
    if isinstance(value, float):
        return format(value, ".10g").replace(".", ",")
    if isinstance(value, str):
        return f"«{value}»"
    return json.dumps(value, ensure_ascii=False)


_CHECKS: tuple[Callable[[ParameterSet, Catalog], list[Issue]], ...] = (
    _check_printer,
    _check_quality,
    _check_materials,
    _check_settings,
    _check_models,
)
