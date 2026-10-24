"""Parse stage-1 requirement values, which arrive as strings (numbers, ranges, yes/no, lists)."""

import re
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_MINUS_SIGNS = ("-", "−")
_LIST_SEPARATORS = re.compile(r"[,;]")


class ValueParseError(TuningError):
    """A requirement value cannot be read as the type the vocabulary expects."""


def parse_numbers(text):
    # type: (str) -> list
    """All numbers in the text. A minus is a sign only at the start or after a space/bracket, so that
    "85-90" is a range while "-10..70" starts below zero."""
    numbers = []
    for match in _NUMBER.finditer(text):
        value = float(match.group().replace(",", "."))
        start = match.start()
        if start > 0 and text[start - 1] in _MINUS_SIGNS and (start == 1 or text[start - 2] in " \t(["):
            value = -value
        numbers.append(value)
    return numbers


def parse_number(text, stricter_end):
    # type: (str, str) -> float
    """A single number, or the stricter end of a two-number range ("upper" or "lower")."""
    numbers = parse_numbers(text)
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return max(numbers) if stricter_end == "upper" else min(numbers)
    raise ValueParseError("expected a number or a range, got %r" % text)


def parse_bool(text, markers):
    # type: (str, dict) -> bool
    """Exact match against the vocabulary markers; anything else is ambiguous."""
    normalized = text.strip().lower()
    if normalized in markers["false"]:
        return False
    if normalized in markers["true"]:
        return True
    raise ValueParseError("expected yes/no, got %r" % text)


def parse_list(text):
    # type: (str) -> list
    items = [item.strip().lower() for item in _LIST_SEPARATORS.split(text)]
    found = [item for item in items if item]
    if not found:
        raise ValueParseError("expected a list, got %r" % text)
    return found


def unit_matches(unit, expected, units):
    # type: (Any, str, dict) -> bool
    if unit is None:
        return False
    normalized = unit.strip().lower()
    return normalized == expected.lower() or normalized in units.get(expected, [])
