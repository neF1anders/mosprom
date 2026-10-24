"""Versioned values shared by application ports; no transport or database types."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def identifier() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Status(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting_user"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"


CARD_SCHEMA_VERSION = "2.0"
DOCUMENT_VERSION = "documents-v3-full-pages"
SELECT_PARAMETERS = "select_parameters"


class Evidence(Value):
    source_id: str
    quote: str = ""
    page: int | None = None
    # Set by the server after verification, never trusted from the model.
    method: Literal["text", "vision", "user", "knowledge"] | None = None
    artifact_id: str | None = None


class Source(Value):
    """Citable input: a chat message, an answer, a document page or a knowledge record.

    ``id`` is the short handle agents cite within one run; ``ref`` is the stable reference
    stored in the card (message id, ``attachment:page``, ``answer:question`` or ``kb:record``).
    """

    id: str
    ref: str
    kind: Literal["message", "answer", "document", "knowledge"]
    text: str = ""
    page: int | None = None
    image: str | None = None
    filename: str = ""
    created_at: datetime | None = None


class Superseded(Value):
    value: str
    unit: str | None = None
    sources: list[Evidence] = Field(default_factory=list)
    reason: str


class Requirement(Value):
    key: str
    label: str = ""
    value: str
    unit: str | None = None
    conditions: str = ""
    mandatory: bool = True
    provenance: Literal["user", "document", "knowledge", "assumption"] = "document"
    sources: list[Evidence] = Field(default_factory=list)
    verified: bool = False
    superseded: list[Superseded] = Field(default_factory=list)


class Assumption(Value):
    text: str
    basis: str = ""
    consequence: str = ""


class Question(Value):
    id: str
    kind: Literal["units", "purpose", "clarify", "verify", "discrepancy"]
    title: str
    impact: str = ""
    options: list[str] = Field(default_factory=list)
    suggested: str | None = None
    basis: str | None = None
    sources: list[Evidence] = Field(default_factory=list)
    requirement_key: str | None = None
    blocking: bool = True
    answer: str | None = None


class Geometry(Value):
    """Summary of the analyzer report; the full report travels as StlAnalysis."""

    readable: bool = False
    units: str = "unknown"
    extents: list[float] = Field(default_factory=list)
    watertight: bool | None = None
    components: int | None = None
    defects: list[str] = Field(default_factory=list)
    surface_area: float | None = None
    volume: float | None = None
    volume_basis: str = ""
    min_wall_sample: float | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    report_id: str | None = None
    preview_id: str | None = None


class StlAnalysis(Value):
    attachment_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: dict[str, Any]


class Remark(Value):
    severity: Literal["critical", "major", "minor"]
    text: str
    requirement_key: str | None = None


class Verdict(Value):
    score: float = Field(ge=0, le=1)
    passed: bool
    reworked: bool = False
    remarks: list[Remark] = Field(default_factory=list)


class SourceFile(Value):
    id: str
    filename: str
    kind: str
    sha256: str


class TaskCard(Value):
    schema_version: str = CARD_SCHEMA_VERSION
    job_id: str
    revision: int
    purpose: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    geometry: Geometry | None = None
    stl_analysis: StlAnalysis | None = None
    verdict: Verdict | None = None
    readiness: Literal["ready", "preliminary", "blocked"] = "blocked"
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: dict[str, list[str]] = Field(default_factory=dict)
    files: list[SourceFile] = Field(default_factory=list)
    versions: dict[str, str] = Field(default_factory=dict)


class Answer(Value):
    title: str
    value: str
    revision: int
    answered_at: datetime = Field(default_factory=now)


Stage = Literal["understanding", "parameters", "validation", "slicing", "gcode", "done"]


class ParametersSummary(Value):
    """What the chat shows of the latest parameter set without loading it."""

    iteration: int
    printing_mode: str
    quality_type: str
    material: str
    changed_settings: int
    unsatisfied: int
    status: Literal["proposed", "infeasible"]
    # "attention" when the last check still found problems or a requirement is not met.
    check: Literal["pending", "ok", "attention"] = "pending"


class ResultSummary(Value):
    """What the chat shows of the slicing and its G-code check without loading them."""

    iteration: int
    sliced: bool
    message: str
    gcode_check: Literal["pending", "ok", "attention"] = "pending"
    # Where the slicer saved the G-code and the project, in its own file system.
    folder: str | None = None
    print_time_seconds: int | None = None
    material_grams: float | None = None
    material_meters: float | None = None

class Job(Value):
    id: str = Field(default_factory=identifier)
    user_id: str
    title: str = "Новое задание"
    # "auto" titles follow the first request and the triage; a rename by the user sticks.
    title_source: Literal["auto", "user"] = "auto"
    deleted: bool = False
    revision: int = 0
    status: Status = Status.DRAFT
    units: str = "unknown"
    active_stl: str | None = None
    card: TaskCard | None = None
    answers: dict[str, Answer] = Field(default_factory=dict)
    # Files are attached without starting work; the next send processes them.
    files_changed: bool = False
    # Between stages the job is queued; it is completed only after the last stage.
    stage: Stage = "understanding"
    parameters: ParametersSummary | None = None
    result: ResultSummary | None = None
    # Stage-one step of the running revision; answers given before "consolidate" join it.
    phase: Literal["triage", "deep", "consolidate", "verify"] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class JobHead(Value):
    id: str
    revision: int
    status: Status


class Message(Value):
    id: str = Field(default_factory=identifier)
    job_id: str
    revision: int
    role: Literal["user", "assistant"]
    # Answers are echoed into the chat but reach the agents through Job.answers, not as text;
    # a message outside the print job is answered once and never read by the agents again.
    kind: Literal["chat", "answers", "offtopic"] = "chat"
    text: str
    created_at: datetime = Field(default_factory=now)


class Attachment(Value):
    active: bool = True
    # Not sent yet: a new upload waiting in the composer, or a removal the next send applies.
    draft: bool = False
    id: str = Field(default_factory=identifier)
    job_id: str
    filename: str
    kind: str
    sha256: str
    size: int
    status: Literal["pending", "completed", "failed"] = "pending"
    error: str | None = None
    fragments: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    parser_version: str = ""


class Event(Value):
    event_id: int = 0
    job_id: str
    revision: int
    type: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class Knowledge(Value):
    id: str
    material_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    property: str
    value: str
    unit: str | None = None
    conditions: str = ""
    method: str = ""
    text: str
    source: str
    version: str = "kb001-v2"
    scope: Literal["grade", "family", "rule", "printer"] = "rule"


class AgentCall(Value):
    """One provider round trip of an agent, stored verbatim for debugging and prompt tuning."""

    job_id: str
    revision: int
    run_id: str
    agent: str
    step: int
    started_at: datetime
    duration_ms: int
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    # A result reused from the cache: no provider call was made.
    cached: bool = False
