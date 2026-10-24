from __future__ import annotations

import builtins
from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol

from ..domain.models import AgentCall, Attachment, Event, Job, JobHead, Knowledge, Message
from ..domain.pipeline import Step


class Jobs(Protocol):
    async def head(self, job_id: str) -> JobHead: ...
    async def get(self, job_id: str, *, user_id: str | None = None, lock: bool = False) -> Job: ...
    async def save(self, job: Job) -> None: ...
    async def list(
        self, user_id: str, before: str | None = None, limit: int = 50
    ) -> builtins.list[Job]: ...


class Messages(Protocol):
    async def add(self, message: Message) -> None: ...
    async def list(
        self, job_id: str, before: int | None = None, limit: int = 100
    ) -> builtins.list[dict[str, Any]]: ...


class Attachments(Protocol):
    async def save(self, attachment: Attachment) -> None: ...
    async def list(self, job_id: str) -> builtins.list[Attachment]: ...


class Receipts(Protocol):
    async def find(self, key: str, payload_hash: str) -> dict[str, Any] | None: ...
    async def remember(self, key: str, payload_hash: str, result: dict[str, Any]) -> None: ...


class Cache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any]) -> None: ...


class Events(Protocol):
    async def append(self, event: Event) -> None: ...
    async def list(self, job_id: str, after: int = 0, limit: int = 100) -> builtins.list[Event]: ...
    async def start(self, job_id: str, revision: int) -> int: ...


class Queue(Protocol):
    async def stage1(self, job_id: str, revision: int, start: bool = False) -> None: ...
    async def stage2(self, job_id: str, revision: int) -> None: ...
    async def cancel_pending(self, job_id: str) -> None: ...


class Library(Protocol):
    async def all(self) -> builtins.list[Knowledge]: ...
    async def put(self, record: Knowledge) -> None: ...


class Traces(Protocol):
    async def record(self, call: AgentCall) -> None: ...
    async def usage(self, job_id: str) -> tuple[int, int]: ...


class StageResults(Protocol):
    async def add(
        self, job_id: str, revision: int, step: Step, payload: dict[str, Any]
    ) -> None: ...
    async def get(self, job_id: str, revision: int, step: Step) -> dict[str, Any] | None: ...
    async def latest(self, job_id: str, revision: int, stage: str) -> dict[str, Any] | None: ...


class UnitOfWork(Protocol):
    jobs: Jobs
    messages: Messages
    attachments: Attachments
    receipts: Receipts
    cache: Cache
    events: Events
    queue: Queue
    knowledge: Library
    traces: Traces
    stage_results: StageResults

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...


UowFactory = Callable[[], UnitOfWork]
