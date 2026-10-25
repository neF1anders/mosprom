from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..domain.parameters import ParameterSet
from ..domain.slicing import SliceReport


class Files(Protocol):
    async def put(self, key: str, chunks: AsyncIterator[bytes], limit: int) -> tuple[str, int]: ...
    async def inspect(self, key: str, kind: str) -> dict[str, Any]: ...
    async def read(self, key: str) -> bytes: ...
    async def remove(self, key: str) -> None: ...
    async def analyze(self, key: str, units: str, cache_key: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ModelReply:
    content: str
    tool_calls: list[dict[str, Any]]
    finish_reason: str
    reasoning: str
    usage: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)


# Each piece of the reasoning as it arrives and the attempt it belongs to, counted from one.
Reasoning = Callable[[str, int], Awaitable[None]]


class ModelClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        agent: str,
        thinking: bool,
        budget: int | None = None,
        on_reasoning: Reasoning | None = None,
    ) -> ModelReply: ...


class Notifier(Protocol):
    """Wakes readers of a job's events when a new one commits, in any process."""

    def watch(self, job_id: str) -> AbstractAsyncContextManager[asyncio.Event]: ...


class Slicer(Protocol):
    """STE Slicer with the AI Assistant plugin, one run at a time.

    ``run`` names the run and its stored files; ``models`` maps an attachment id of the set
    to its stored file. A slicer that is not running, fails a step or runs out of time is
    reported, not raised.
    """

    async def slice(
        self, run: str, parameter_set: ParameterSet, models: dict[str, str]
    ) -> SliceReport: ...


@dataclass(frozen=True)
class ResultFolder:
    """A finished project's own folder: ``path`` here, ``shown`` as the slicer's machine sees it."""

    path: Path
    shown: str


class ResultFolders(Protocol):
    """The folders the user keeps, one per finished project and named after its part."""

    async def reserve(self, part: str) -> ResultFolder: ...
    async def write(self, folder: ResultFolder, name: str, data: bytes) -> None: ...
    async def discard(self, folder: ResultFolder) -> None: ...
