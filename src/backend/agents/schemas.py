"""What each agent returns. Lenient by design: unknown fields are ignored, numbers become text."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)


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
    provenance: Literal["user", "document", "knowledge", "assumption"] = "document"
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
    blocking: bool = True
    # Set when the question asks for one of the fields of the quick triage.
    field: str | None = None


class Draft(Output):
    purpose: str = ""
    requirements: list[DraftRequirement] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    assumptions: list[DraftAssumption] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    questions: list[DraftQuestion] = Field(default_factory=list)


class TriageField(Output):
    field: str
    value: str = ""
    source_id: str | None = None
    quote: str = ""


class TriageProposal(Output):
    field: str
    options: list[str] = Field(default_factory=list)
    suggested: str | None = None
    basis: str | None = None


class Triage(Output):
    title: str = ""
    fields: list[TriageField] = Field(default_factory=list)
    questions: list[TriageProposal] = Field(default_factory=list)


class DomainReading(Output):
    """What one domain analyst read in the sources on its own, without the draft."""

    requirements: list[DraftRequirement] = Field(default_factory=list)
    questions: list[DraftQuestion] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class RequirementChange(DraftRequirement):
    id: str


class Removal(Output):
    id: str
    reason: str = ""


class Patch(Output):
    """The consolidator's edit of the draft; the server applies it by requirement id."""

    purpose: str | None = None
    add: list[DraftRequirement] = Field(default_factory=list)
    change: list[RequirementChange] = Field(default_factory=list)
    remove: list[Removal] = Field(default_factory=list)
    preferences: list[str] | None = None
    production_constraints: list[str] | None = None
    assumptions: list[DraftAssumption] | None = None
    unknowns: list[str] | None = None
    questions: list[DraftQuestion] | None = None


class DiscrepancyItem(Output):
    kind: Literal["tz_vs_stl", "capability", "defect_vs_purpose"]
    requirement_key: str | None = None
    title: str
    impact: str = ""
    options: list[str] = Field(default_factory=list)
    suggested: str | None = None
    basis: str | None = None
    sources: list[Citation] = Field(default_factory=list)


class Discrepancies(Output):
    discrepancies: list[DiscrepancyItem] = Field(default_factory=list)


class Reading(Output):
    key: str
    value: str = ""
    unit: str | None = None
    legible: bool = True


class SecondReading(Output):
    readings: list[Reading] = Field(default_factory=list)


class JudgeRemark(Output):
    severity: Literal["critical", "major", "minor"]
    text: str
    requirement_key: str | None = None


class JudgeVerdict(Output):
    score: float = Field(ge=0, le=1)
    remarks: list[JudgeRemark] = Field(default_factory=list)
