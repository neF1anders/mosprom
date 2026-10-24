"""Requirement codes that stage one and parameter selection share.

Stage one uses a code when a requirement means the same property, so that parameter
selection can read it without guessing; anything else keeps its own key and is reported as
not taken into account.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import Value


class RequirementKey(Value):
    key: str
    kind: Literal["number", "flag", "list", "choice", "text"]
    title: str
    unit: str | None = None
    # Which end of a range binds: the upper one for "at least", the lower one for "at most".
    strict: Literal["upper", "lower"] | None = None
    options: list[str] = Field(default_factory=list)


class RequirementKeys(Value):
    keys: list[RequirementKey]

    def get(self, key: str) -> RequirementKey | None:
        return next((entry for entry in self.keys if entry.key == key), None)
