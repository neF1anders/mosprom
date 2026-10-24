"""In-memory doubles for agent tests; the provider is scripted per agent name."""

from __future__ import annotations

import inspect
import json
from collections import defaultdict
from typing import Any

from src.backend.agents.runner import RunContext
from src.backend.ports.operations import ModelReply


def reply(content: Any = "", tool_calls=None, finish_reason: str | None = None) -> ModelReply:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    reason = finish_reason or ("tool_calls" if tool_calls else "stop")
    raw = {"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 1}}
    return ModelReply(text, tool_calls or [], reason, "думаю", {"total_tokens": 1}, raw)


def call(name: str, arguments: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


class ScriptedModel:
    def __init__(self, script: dict[str, list]):
        self.script = {agent: list(replies) for agent, replies in script.items()}
        self.requests: dict[str, list] = defaultdict(list)

    async def complete(
        self, messages, tools, *, agent: str, thinking: bool, budget: int | None = None
    ) -> ModelReply:
        self.requests[agent].append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": tools,
                "thinking": thinking,
                "budget": budget,
            }
        )
        replies = self.script[agent]
        item = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(messages)
        return await item if inspect.isawaitable(item) else item


class Traces:
    def __init__(self):
        self.calls = []

    async def record(self, call):
        self.calls.append(call)


class Cache:
    def __init__(self):
        self.values: dict[str, Any] = {}

    async def get(self, key):
        return self.values.get(key)

    async def put(self, key, value):
        self.values.setdefault(key, value)


class FakeUow:
    def __init__(self):
        self.traces = Traces()
        self.cache = Cache()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def commit(self):
        return None


def context(**extra) -> RunContext:
    events = []

    async def check():
        return None

    async def event(type, message, status="running", **data):
        events.append((type, message, status, data))

    ctx = RunContext(job_id="j", revision=1, run_id="r", check=check, event=event, **extra)
    ctx.recorded = events  # type: ignore[attr-defined]
    return ctx
