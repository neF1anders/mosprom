"""Contracts between parameter selection (stage two), its check (stage three) and the slicer.

``ParameterSet`` 0.2 is the checker's 0.1 plus the fields stage two already reports: its
status, unmet requirements, warnings, material alternatives and checks, the orientation
candidate and, on the second pass, how each constraint of the check was applied.
``Feedback`` is what the check returns to stage two for its second and last pass.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import Value

MAX_ITERATIONS = 2

# Every value cites where it came from; the check rejects any other form.
SourceRef = Annotated[
    str,
    StringConstraints(pattern=r"^(requirement|rule|constraint|assumption):[\w\-.]+$|^default$"),
]
ConstraintId = Annotated[str, StringConstraints(pattern=r"^[\w\-.]+$")]
Scalar = bool | int | float | str
Reason = Annotated[str, StringConstraints(pattern=r"\S")]


class Reasoned(Value):
    why: Reason
    source: SourceRef


class CardRef(Value):
    job_id: str
    revision: int


class PrintingMode(Reasoned):
    value: Literal["classic", "cylindrical", "cylindrical_full"]


class Quality(Reasoned):
    quality_type: str


class MaterialCheck(Value):
    requirement_id: str
    key: str
    hard: bool
    status: Literal["ok", "warn", "fail", "unknown"]
    detail: str


class Alternative(Value):
    id: str
    why: str


class Material(Reasoned):
    id: str
    alternatives: list[Alternative] = Field(default_factory=list)
    checks: list[MaterialCheck] = Field(default_factory=list)


class Setting(Reasoned):
    value: Scalar | list[Any]
    unit: str | None = None
    scope: str | None = None


class Transform(Value):
    rotation: list[list[float]]
    position: list[float]
    scale: list[float]


class PlacedModel(Reasoned):
    id: str
    attachment_id: str
    extruder: int
    orientation_candidate: str
    transform: Transform


class SelectionAssumption(Value):
    id: str
    text: str
    basis: str


class Unsatisfied(Value):
    requirement_id: str
    why: str
    conflicts_with: str | None = None


class AppliedConstraint(Value):
    id: str
    result: Literal["applied", "not_applied"]
    why: str


class ParameterSet(Value):
    contract: Literal["stage2.parameter_set"] = "stage2.parameter_set"
    version: Literal["0.2"] = "0.2"
    card_ref: CardRef
    iteration: int = Field(ge=1, le=MAX_ITERATIONS)
    printer: str
    printing_mode: PrintingMode
    quality: Quality
    materials: dict[str, Material]
    settings: dict[str, Setting]
    models: list[PlacedModel]
    assumptions: list[SelectionAssumption] = Field(default_factory=list)
    status: Literal["proposed", "infeasible"]
    unsatisfied: list[Unsatisfied] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    applied_constraints: list[AppliedConstraint] | None = None

    def published(self) -> dict[str, Any]:
        """The JSON form: optional fields that are not set are left out."""
        return self.model_dump(mode="json", exclude_none=True)


class Constraint(Value):
    id: ConstraintId
    key: str
    op: Literal["eq", "ne", "min", "max", "in"]
    value: Any
    reason: str = ""
    severity: Literal["error", "warning"] = "error"

    @model_validator(mode="after")
    def _choice_is_a_list(self) -> Constraint:
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("op in needs a list of values")
        return self


class Exclusion(Value):
    type: str
    candidate: str | None = None
    reason: str = ""


class FeedbackWarning(Value):
    key: str
    reason: str


class Feedback(Value):
    contract: Literal["stage3.feedback"] = "stage3.feedback"
    version: Literal["0.1"] = "0.1"
    iteration: int = Field(ge=1, le=MAX_ITERATIONS)
    result: Literal["ok", "needs_changes"]
    constraints: list[Constraint] = Field(default_factory=list)
    exclude: list[Exclusion] = Field(default_factory=list)
    warnings: list[FeedbackWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _constraint_ids_are_unique(self) -> Feedback:
        ids = [constraint.id for constraint in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint ids must be unique")
        return self


class Issue(Value):
    """One finding of the check. ``kind`` is machine-readable; ``message`` is for people.

    ``where`` is the place in the parameter set, ``key`` the slicer key or choice a feedback
    item names and ``bound`` what that item needs: a limit, the allowed values, the value to
    set or the orientation candidate to drop.
    """

    level: Literal["error", "warning", "info"]
    where: str
    kind: str
    message: str
    key: str | None = None
    bound: Any = None
