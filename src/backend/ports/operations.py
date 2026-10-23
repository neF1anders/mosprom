from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


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


class ModelClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        agent: str,
        thinking: bool,
        budget: int | None = None,
    ) -> ModelReply: ...
