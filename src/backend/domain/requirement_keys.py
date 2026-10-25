from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from .models import Value
from .units import dimension


class RequirementKey(Value):
    key: str
    kind: Literal["number", "flag", "list", "choice", "text"]
    title: str
    unit: str | None = None
    # какой конец диапазона
    strict: Literal["upper", "lower"] | None = None
    options: list[str] = Field(default_factory=list)
    # формулировки спецификации кода
    hint: str = ""


# число или диапазон
NUMBER = re.compile(r"^[^0-9]*-?\d+([.,]\d+)?([^0-9]+-?\d+([.,]\d+)?)?[^0-9]*$")
YES = {"да", "yes", "true", "1"}
NO = {"нет", "no", "false", "0"}


class RequirementKeys(Value):
    # версия словаря
    version: str
    keys: list[RequirementKey]

    def get(self, key: str) -> RequirementKey | None:
        return next((entry for entry in self.keys if entry.key == key), None)

    def unit_mismatch(self, key: str, unit: str | None) -> str | None:
        """Единица кода при несовпадении."""
        entry = self.get(key)
        if entry is None or entry.unit is None or dimension(unit) == dimension(entry.unit):
            return None
        return entry.unit

    def normalise(self, key: str, value: str, unit: str | None) -> tuple[str, str | None] | None:
        """Значение в читаемом виде."""
        entry = self.get(key)
        text = value.strip()
        if entry is None or not text:
            return None
        if entry.kind == "number":
            return _number(entry, text, unit)
        if entry.kind == "flag":
            return _flag(text)
        if entry.kind == "choice":
            return _choice(entry, text)
        if entry.kind == "list" and entry.options:
            return _options(entry, text)
        return text, unit


def _number(entry: RequirementKey, text: str, unit: str | None) -> tuple[str, str | None] | None:
    if not NUMBER.match(text):
        return None
    if entry.unit is None:
        return text, unit
    if not unit:
        return text, entry.unit
    return (text, unit) if dimension(unit) == dimension(entry.unit) else None


def _flag(text: str) -> tuple[str, None] | None:
    word = text.casefold()
    if word in YES:
        return "да", None
    return ("нет", None) if word in NO else None


def _choice(entry: RequirementKey, text: str) -> tuple[str, None] | None:
    word = text.casefold()
    return (word, None) if word in entry.options else None


def _options(entry: RequirementKey, text: str) -> tuple[str, None] | None:
    items = [item.strip().casefold() for item in re.split(r"[,;]", text)]
    kept = list(dict.fromkeys(item for item in items if item in entry.options))
    return (", ".join(kept), None) if kept else None
