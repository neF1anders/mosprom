"""Requirement codes that stage one and parameter selection share.

Stage one uses a code when a requirement means the same property, so that parameter
selection can read it without guessing; anything else keeps its own key and is reported as
not taken into account.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import Value
from .units import dimension


class RequirementKey(Value):
    key: str
    kind: Literal["number", "flag", "list", "choice", "text"]
    title: str
    unit: str | None = None
    # Which end of a range binds: the upper one for "at least", the lower one for "at most".
    strict: Literal["upper", "lower"] | None = None
    options: list[str] = Field(default_factory=list)
    # How a wording of the specification maps to this code, shown to the model with the code.
    hint: str = ""


class RequirementKeys(Value):
    # Recorded in the card so that parameter selection knows which dictionary it was built with.
    version: str
    keys: list[RequirementKey]

    def get(self, key: str) -> RequirementKey | None:
        return next((entry for entry in self.keys if entry.key == key), None)

    def unit_mismatch(self, key: str, unit: str | None) -> str | None:
        """The code's unit when a stated unit measures another quantity, otherwise None.

        Parameter selection reads a coded number in the code's unit only, so a temperature
        code given in millimetres, or with no unit, cannot be taken into account.
        """
        entry = self.get(key)
        if entry is None or entry.unit is None or dimension(unit) == dimension(entry.unit):
            return None
        return entry.unit
