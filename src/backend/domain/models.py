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
    # ставит сервер
    method: Literal["text", "vision", "user", "knowledge"] | None = None
    artifact_id: str | None = None


class Source(Value):
    """Цитируемый вход: сообщение или документ."""

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
    """Сводка отчёта анализатора STL."""

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


class WaivedQuestion(Value):
    """Вопрос, который проверяющий не задал."""

    title: str
    reason: str


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
    waived: list[WaivedQuestion] = Field(default_factory=list)
    geometry: Geometry | None = None
    stl_analysis: StlAnalysis | None = None
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
# итог конвейера
Outcome = Literal["ready", "attention", "parameters_attention", "not_sliced"]


class ParametersSummary(Value):
    """Сводка последнего набора параметров."""

    iteration: int
    printing_mode: str
    quality_type: str
    material: str
    changed_settings: int
    unsatisfied: int
    status: Literal["proposed", "infeasible"]
    # внимание при проблемах
    check: Literal["pending", "ok", "attention"] = "pending"


class ResultSummary(Value):
    """Сводка нарезки и проверки."""

    iteration: int
    sliced: bool
    message: str
    gcode_check: Literal["pending", "ok", "attention"] = "pending"
    # пути в слайсере
    folder: str | None = None
    print_time_seconds: int | None = None
    material_grams: float | None = None
    material_meters: float | None = None


class Project(Value):
    """Одна часть работы чата."""

    number: int
    title: str
    notes: str = ""
    first_message: int = 0
    revision: int = 0
    answers: dict[str, str] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=now)


class Job(Value):
    id: str = Field(default_factory=identifier)
    user_id: str
    title: str = "Новое задание"
    # название по запросу
    title_source: Literal["auto", "user"] = "auto"
    deleted: bool = False
    revision: int = 0
    status: Status = Status.DRAFT
    active_stl: str | None = None
    card: TaskCard | None = None
    answers: dict[str, Answer] = Field(default_factory=dict)
    # файлы без запуска
    files_changed: bool = False
    # очередь между этапами
    stage: Stage = "understanding"
    # ревизия текущей работы
    work_revision: int = 0
    parameters: ParametersSummary | None = None
    result: ResultSummary | None = None
    outcome: Outcome | None = None
    error: str | None = None
    # части чата
    projects: list[Project] = Field(default_factory=list)
    # последнее отвеченное сообщение
    answered: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    @property
    def project(self) -> Project | None:
        return self.projects[-1] if self.projects else None


class JobHead(Value):
    id: str
    revision: int
    status: Status


class Message(Value):
    id: str = Field(default_factory=identifier)
    job_id: str
    revision: int
    role: Literal["user", "assistant"]
    # ответы через Job
    # служебные виды сообщений
    kind: Literal["chat", "answers", "gate", "offtopic", "steer", "report"] = "chat"
    text: str
    # файлы сообщения
    attachment_ids: list[str] = Field(default_factory=list)
    # ход ассистента
    turn: str | None = None
    created_at: datetime = Field(default_factory=now)


class QueuedMessage(Value):
    """Сообщение, набранное во время работы."""

    id: str = Field(default_factory=identifier)
    job_id: str
    text: str
    attachment_ids: list[str] = Field(default_factory=list)
    status: Literal["queued", "delivering"] = "queued"
    claim: str | None = None
    claimed_at: datetime | None = None
    # сбои доставки
    attempts: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Attachment(Value):
    active: bool = True
    # ещё не отправлено
    draft: bool = False
    # проект файла
    project: int | None = None
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
    """Один вызов провайдера агентом."""

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
    # результат из кеша
    cached: bool = False
