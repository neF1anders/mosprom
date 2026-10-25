from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from ..domain.requirement_keys import RequirementKeys


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    @model_validator(mode="before")
    @classmethod
    def defaults_for_nulls(cls, data: Any) -> Any:
        """Значения по умолчанию вместо null."""
        if not isinstance(data, dict):
            return data
        fields = cls.model_fields
        return {
            name: value
            for name, value in data.items()
            if value is not None or name not in fields or fields[name].is_required()
        }


class Citation(Output):
    source_id: str
    page: int | None = None
    quote: str


class DraftRequirement(Output):
    key: str
    label: str = ""
    value: str
    unit: str | None = None
    conditions: str = ""
    mandatory: bool = True
    sources: list[Citation] = Field(default_factory=list)


class DraftAssumption(Output):
    text: str
    basis: str = ""
    consequence: str = ""


class DraftQuestion(Output):
    title: str
    impact: str = ""
    options: list[str] = Field(default_factory=list)
    suggested: str | None = None
    basis: str | None = None


class Draft(Output):
    purpose: str = ""
    requirements: list[DraftRequirement] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    assumptions: list[DraftAssumption] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    questions: list[DraftQuestion] = Field(default_factory=list)


def _lenient(data: Any) -> Any:
    """Мягкое приведение значения кода."""
    data = dict(data) if isinstance(data, dict) else {"value": data}
    value = data.get("value")
    if isinstance(value, list):
        data["value"] = ", ".join(map(str, value))
    elif isinstance(value, bool):
        data["value"] = "да" if value else "нет"
    if isinstance(data.get("quote"), list):
        data["quote"] = " ".join(map(str, data["quote"]))
    return data


class CodeValue(Output):
    """Значение одного кода требования."""

    value: str
    unit: str | None = None
    label: str = ""
    conditions: str = ""
    mandatory: bool = True
    source_id: str | None = None
    page: int | None = None
    quote: str = ""
    inferred: bool = False
    basis: str = ""

    @model_validator(mode="before")
    @classmethod
    def lenient(cls, data: Any) -> Any:
        return _lenient(data)


class Codes(Output):
    """Поле на каждый код словаря."""

    @model_validator(mode="before")
    @classmethod
    def per_code(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return {}
        kept: dict[str, CodeValue] = {}
        for code, value in data.items():
            if code not in cls.model_fields or value is None:
                continue
            if isinstance(value, dict) and value.get("value") is None:
                continue
            try:
                kept[code] = CodeValue.model_validate(value)
            except ValidationError:
                continue
        return kept

    def filled(self) -> dict[str, CodeValue]:
        return {code: value for code, value in self if isinstance(value, CodeValue)}


class DraftWithCodes(Draft):
    codes: Codes = Field(default_factory=Codes)


def draft_with_codes(keys: RequirementKeys) -> type[DraftWithCodes]:
    """Схема черновика со всеми кодами."""
    fields: Any = {entry.key: (CodeValue | None, None) for entry in keys.keys}
    codes = create_model("Codes", __base__=Codes, **fields)
    model = create_model(
        "DraftWithCodes", __base__=DraftWithCodes, codes=(codes, Field(default_factory=codes))
    )
    return cast(type[DraftWithCodes], model)


class RequirementChange(DraftRequirement):
    id: str


class Removal(Output):
    id: str
    reason: str = ""


class CodeFix(Output):
    """Исправление одного кода проверяющим."""

    code: str
    value: str | None = None
    unit: str | None = None
    source_id: str | None = None
    quote: str = ""
    inferred: bool = True
    basis: str = ""
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def lenient(cls, data: Any) -> Any:
        return _lenient(data) if isinstance(data, dict) else data


class ReviewQuestion(DraftQuestion):
    kind: str = "clarify"
    requirement_key: str | None = None
    # идентификатор оставляемого вопроса
    source: str | None = None


class Waived(Output):
    """Вопрос, который не задаём."""

    id: str
    reason: str


class Review(Output):
    """Правка карточки от проверяющего."""

    change: list[RequirementChange] = Field(default_factory=list)
    remove: list[Removal] = Field(default_factory=list)
    add: list[DraftRequirement] = Field(default_factory=list)
    code_fixes: list[CodeFix] = Field(default_factory=list)
    assumptions: list[DraftAssumption] = Field(default_factory=list)
    questions: list[ReviewQuestion] = Field(default_factory=list)
    waived: list[Waived] = Field(default_factory=list)
