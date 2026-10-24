"""Deterministic unit conversion and quantity comparison within one physical dimension."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

STL_UNITS = ("mm", "cm", "m", "inch")

_LINEAR: dict[str, tuple[str, str]] = {
    "мкм": ("length", "0.001"),
    "um": ("length", "0.001"),
    "mm": ("length", "1"),
    "мм": ("length", "1"),
    "cm": ("length", "10"),
    "см": ("length", "10"),
    "m": ("length", "1000"),
    "м": ("length", "1000"),
    "inch": ("length", "25.4"),
    "in": ("length", "25.4"),
    "дюйм": ("length", "25.4"),
    "n": ("force", "1"),
    "н": ("force", "1"),
    "kn": ("force", "1000"),
    "кн": ("force", "1000"),
    "kgf": ("force", "9.80665"),
    "кгс": ("force", "9.80665"),
    "n·m": ("torque", "1"),
    "nm": ("torque", "1"),
    "н·м": ("torque", "1"),
    "нм": ("torque", "1"),
    "n·mm": ("torque", "0.001"),
    "н·мм": ("torque", "0.001"),
    "kgf·m": ("torque", "9.80665"),
    "кгс·м": ("torque", "9.80665"),
    "mg": ("mass", "0.001"),
    "мг": ("mass", "0.001"),
    "g": ("mass", "1"),
    "г": ("mass", "1"),
    "kg": ("mass", "1000"),
    "кг": ("mass", "1000"),
    "pa": ("pressure", "1"),
    "па": ("pressure", "1"),
    "kpa": ("pressure", "1000"),
    "кпа": ("pressure", "1000"),
    "mpa": ("pressure", "1000000"),
    "мпа": ("pressure", "1000000"),
    "bar": ("pressure", "100000"),
    "бар": ("pressure", "100000"),
    "kg/m3": ("density", "1"),
    "кг/м3": ("density", "1"),
    "g/cm3": ("density", "1000"),
    "г/см3": ("density", "1000"),
    "s": ("time", "1"),
    "с": ("time", "1"),
    "min": ("time", "60"),
    "мин": ("time", "60"),
    "h": ("time", "3600"),
    "ч": ("time", "3600"),
    "rpm": ("rotation", "1"),
    "об/мин": ("rotation", "1"),
}
_TEMPERATURE = {"c", "°c", "с°", "°с", "k", "к", "f", "°f"}
# A number does not continue a word, a list or a dotted version ("v.2", "1.5.7"), but may
# follow the two dots of a range ("-10..70").
_NUMBER = re.compile(r"(?<![\w,])(?<![^.]\.)(?<!^\.)-?\d+(?:[.,]\d+)?")
# A word right after a number, such as °C, кг/м³ or Н·м; only known units count.
_UNIT = re.compile(r"(?<=\d)\s*(°?\s?[^\W\d_]+(?:[/·*⋅][^\W\d_]+)?[³3]?)")


def canonical(unit: str | None) -> str:
    text = (unit or "").strip().casefold()
    for old, new in (("³", "3"), ("*", "·"), ("⋅", "·"), (" ", ""), ("ньютон", "н")):
        text = text.replace(old, new)
    return {"мм.": "мм", "см.": "см", "м.": "м", "°": "°c", "градc": "°c"}.get(text, text)


def dimension(unit: str | None) -> str | None:
    unit = canonical(unit)
    if unit in _TEMPERATURE:
        return "temperature"
    entry = _LINEAR.get(unit)
    return entry[0] if entry else None


def convert(value: Decimal, source: str, target: str) -> Decimal:
    source, target = canonical(source), canonical(target)
    if source in _TEMPERATURE or target in _TEMPERATURE:
        if source not in _TEMPERATURE or target not in _TEMPERATURE:
            raise ValueError("Температуру можно переводить только в температуру")
        return _from_kelvin(_to_kelvin(value, source), target)
    if source not in _LINEAR or target not in _LINEAR:
        raise ValueError("Неизвестная единица измерения")
    (left, factor), (right, divisor) = _LINEAR[source], _LINEAR[target]
    if left != right:
        raise ValueError(f"Нельзя перевести {left} в {right}")
    return value * Decimal(factor) / Decimal(divisor)


def _to_kelvin(value: Decimal, unit: str) -> Decimal:
    if unit in {"k", "к"}:
        return value
    if unit in {"f", "°f"}:
        return (value - 32) * Decimal(5) / Decimal(9) + Decimal("273.15")
    return value + Decimal("273.15")


def _from_kelvin(value: Decimal, unit: str) -> Decimal:
    if unit in {"k", "к"}:
        return value
    if unit in {"f", "°f"}:
        return (value - Decimal("273.15")) * Decimal(9) / Decimal(5) + 32
    return value - Decimal("273.15")


def numbers(text: str) -> list[Decimal]:
    found = []
    for raw in _NUMBER.findall(text):
        try:
            found.append(Decimal(raw.replace(",", ".")))
        except InvalidOperation:
            continue
    return found


def plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def restated(text: str, unit: str | None) -> list[Decimal]:
    """Numbers of a quote in ``unit`` when the quote gives them in another scale of the same
    quantity: «не более 1200 кг/м3» in g/cm3 is 1.2. A number belongs to the unit after it, so
    «от 1 до 2 см» gives both bounds. Numbers already in this scale are not repeated."""
    kind, start = dimension(unit), 0
    found: list[Decimal] = []
    for match in _UNIT.finditer(text):
        stated = canonical(match.group(1))
        if dimension(stated) is None:
            continue
        if dimension(stated) == kind and not _same_scale(stated, unit or ""):
            found += [convert(n, stated, unit or "") for n in numbers(text[start : match.start()])]
        start = match.end()
    return found


def _same_scale(unit: str, other: str) -> bool:
    return convert(Decimal(0), unit, other) == 0 and convert(Decimal(1), unit, other) == 1


def quantity_key(value: str, unit: str | None) -> tuple[str, tuple[str, ...]]:
    """Comparable identity of a stated quantity; ranges keep every bound."""
    found = numbers(value)
    if not found:
        return ("text", (" ".join(value.casefold().split()),))
    kind = dimension(unit)
    if kind is None:
        return (canonical(unit), tuple(plain(n) for n in found))
    base = {"temperature": "°c"}.get(kind) or next(
        name for name, (dim, factor) in _LINEAR.items() if dim == kind and factor == "1"
    )
    return (kind, tuple(plain(convert(n, unit or "", base)) for n in found))
