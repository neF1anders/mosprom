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


class Evidence(Value):
    source_id: str
    quote: str = ""
    page: int | None = None
    method: Literal["text", "vision", "user"] = "text"
    artifact_id: str | None = None


class Requirement(Value):
    label: str = ""
    key: str
    value: str
    unit: str | None = None
    conditions: str = ""
    mandatory: bool = True
    provenance: Literal["user", "document", "measurement", "knowledge", "assumption"] = "document"
    sources: list[Evidence] = Field(default_factory=list)
    verified: bool = True


class Question(Value):
    id: str
    title: str
    reason: str
    options: list[str] = Field(default_factory=list)
    affected_actions: list[str] = Field(default_factory=lambda: ["select_parameters"])
    suggested: str | None = None
    basis: str | None = None
    answer: str | None = None


class Conflict(Value):
    id: str
    title: str
    options: list[str]
    sources: list[Evidence] = Field(default_factory=list)
    affected_actions: list[str] = Field(default_factory=lambda: ["select_parameters"])
    resolution: str | None = None
    resolved: bool = False


class Geometry(Value):
    readable: bool = False
    units: str = "unknown"
    coordinate_unit: Literal["unknown", "mm"] = "unknown"
    extents: list[float] = Field(default_factory=list)
    defects: list[str] = Field(default_factory=list)
    physical_volume_confirmed: bool = False
    report_id: str | None = None
    preview_id: str | None = None
    limitations: list[str] = Field(default_factory=list)


class InterpretationCard(Value):
    # Keep the established model-output contract independent of transport additions.
    model_config = ConfigDict(extra="forbid", title="TaskCard")
    schema_version: str = "1.0"
    rules_version: str = "1"
    knowledge_version: str = "kb001-v1"
    revision: int = 0
    purpose: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    geometry: Geometry = Field(default_factory=Geometry)
    source_versions: list[dict[str, str]] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: dict[str, list[str]] = Field(default_factory=dict)
    readiness: Literal["ready", "preliminary", "blocked"] = "blocked"


CARD_SCHEMA_VERSION = "1.2"
DOCUMENT_VERSION = "documents-v2-vision"


class StlAnalysis(Value):
    attachment_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: dict[str, Any]


class TaskCard(InterpretationCard):
    schema_version: str = CARD_SCHEMA_VERSION
    stl_analysis: StlAnalysis | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    resolutions: dict[str, str] = Field(default_factory=dict)


class Job(Value):
    id: str = Field(default_factory=identifier)
    title: str = "Новое задание"
    revision: int = 0
    status: Status = Status.DRAFT
    units: str = "unknown"
    active_stl: str | None = None
    card: TaskCard | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    resolutions: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    handoff: str = "not_ready"
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
    role: str
    text: str
    created_at: datetime = Field(default_factory=now)


class Attachment(Value):
    active: bool = True
    id: str = Field(default_factory=identifier)
    job_id: str
    filename: str
    kind: str
    sha256: str
    size: int
    status: str = "pending"
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


class Work(Value):
    id: str = Field(default_factory=identifier)
    job_id: str
    revision: int
    owner: str = ""
    attempts: int = 0


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
    version: str = "kb001-v1"
    scope: Literal["grade", "family", "rule", "printer", "example"] = "rule"
