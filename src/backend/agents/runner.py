"""One generic loop for every agent: tool calls, json-repair parsing, limits and tracing."""

from __future__ import annotations

import hashlib
import json
import time
import types
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import json_repair
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..domain.errors import AppError
from ..domain.models import AgentCall, Source, now
from ..ports.operations import ModelClient, ModelReply
from ..ports.persistence import UowFactory

if TYPE_CHECKING:
    from .tools import ToolBox

T = TypeVar("T", bound=BaseModel)
PROMPTS = Path(__file__).parent / "prompts"
FINAL_STEP = (
    "Инструменты больше недоступны. Верни итоговый JSON по схеме, отметь неизвестное как "
    "неизвестное."
)


@dataclass(frozen=True)
class AgentSpec:
    """The last of max_steps is always offered without tools, so every run ends with an answer."""

    name: str
    title: str
    output: type[BaseModel]
    tools: tuple[str, ...] = ()
    max_steps: int = 10
    thinking: bool = True
    # Reasoning token cap; it bounds the slowest step, not the typical one.
    budget: int | None = None


@dataclass
class RunContext:
    """State shared by the agents of one stage-one run."""

    job_id: str
    revision: int
    run_id: str
    check: Callable[[], Awaitable[None]]
    event: Callable[..., Awaitable[None]]
    sources: dict[str, Source] = field(default_factory=dict)
    stl_report: dict[str, Any] | None = None
    images: dict[str, str] = field(default_factory=dict)


@cache
def prompt(name: str) -> str:
    """Shared rules first, then the role; the digest of this text versions the card."""
    common = (PROMPTS / "common.md").read_text(encoding="utf-8")
    return common + "\n" + (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class AgentRunner:
    def __init__(self, model: ModelClient, tools: ToolBox, uow: UowFactory, version: str = ""):
        self.model, self.tools, self.uow, self.version = model, tools, uow, version

    async def run(self, spec: AgentSpec, content: list[dict[str, Any]], ctx: RunContext) -> Any:
        """An agent's result is reused while its prompt, model and own input stay the same.

        Each agent sees only the data it depends on, so an answer or a new STL unit reruns
        just the agents that read it.
        """
        key = self._key(spec, content, ctx)
        async with self.uow() as uow:
            cached = await uow.jobs.cache(key)
        if cached is not None:
            return spec.output.model_validate(cached)
        output = await self._run(spec, content, ctx)
        async with self.uow() as uow:
            await uow.jobs.cache_put(key, output.model_dump(mode="json"))
            await uow.commit()
        return output

    def _key(self, spec: AgentSpec, content: list[dict[str, Any]], ctx: RunContext) -> str:
        data = json.dumps(
            [
                "agent",
                spec.name,
                prompt(spec.name),
                spec.output.model_json_schema(),
                spec.tools,
                spec.thinking,
                spec.budget,
                self.version,
                redact(content, ctx.images),
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return "agent:" + hashlib.sha256(data.encode()).hexdigest()

    async def _run(self, spec: AgentSpec, content: list[dict[str, Any]], ctx: RunContext) -> Any:
        schema = json.dumps(spec.output.model_json_schema(), ensure_ascii=False)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt(spec.name) + "\n\nСхема ответа JSON\n" + schema},
            {"role": "user", "content": content},
        ]
        seen: dict[str, dict[str, Any]] = {}
        for step in range(1, spec.max_steps + 1):
            await ctx.check()
            final = step == spec.max_steps
            schemas = [] if final else self.tools.schemas(spec.tools)
            if final and spec.tools:
                messages.append({"role": "user", "content": FINAL_STEP})
            trace = Trace(spec, ctx, step, messages)
            try:
                reply = await self.model.complete(
                    messages,
                    schemas,
                    agent=spec.name,
                    thinking=spec.thinking,
                    budget=spec.budget,
                )
            except AppError as exc:
                await self._record(trace.done(None, [], exc.message))
                raise
            if not (reply.tool_calls and schemas):
                await self._record(trace.done(reply, [], None))
                if reply.finish_reason == "length":
                    raise AppError("Ответ модели оборван по длине", "model_truncated", 502)
                output, dropped = parse_output(reply.content, spec.output)
                if dropped:
                    await ctx.event(
                        "agent.dropped", f"{spec.title}, часть ответа отброшена", dropped=dropped
                    )
                return output
            executed = await self._tools(spec, reply, messages, ctx, seen)
            await self._record(trace.done(reply, executed, None))

    async def _tools(self, spec, reply, messages, ctx, seen) -> list[dict[str, Any]]:
        messages.append(
            {"role": "assistant", "content": reply.content, "tool_calls": reply.tool_calls}
        )
        executed, images = [], []
        for call in reply.tool_calls:
            name = call["function"]["name"]
            arguments = json_repair.loads(call["function"].get("arguments") or "{}")
            # A repeated identical call gets the same answer instead of a new execution.
            signature = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen[signature] = await self._call_tool(spec, name, arguments, ctx)
            result = dict(seen[signature])
            images.extend(result.pop("images", []))
            executed.append({"name": name, "arguments": arguments, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        if images:
            messages.append({"role": "user", "content": images})
        return executed

    async def _call_tool(self, spec, name, arguments, ctx) -> dict[str, Any]:
        if name not in spec.tools:
            return {"error": "Этот инструмент недоступен"}
        await ctx.event(
            "tool.called",
            f"{spec.title}, {self.tools.title(name)}",
            agent=spec.name,
            tool=name,
            arguments=arguments,
        )
        try:
            return await self.tools.call(name, arguments, ctx)
        except AppError as exc:
            return {"error": exc.message}

    async def _record(self, call: AgentCall) -> None:
        async with self.uow() as uow:
            await uow.traces.record(call)
            await uow.commit()


class Trace:
    def __init__(self, spec: AgentSpec, ctx: RunContext, step: int, messages: list):
        self.spec, self.ctx, self.step = spec, ctx, step
        self.request = {"messages": redact(messages, ctx.images)}
        self.started, self.clock = now(), time.perf_counter()

    def done(self, reply: ModelReply | None, tools: list, error: str | None) -> AgentCall:
        return AgentCall(
            job_id=self.ctx.job_id,
            revision=self.ctx.revision,
            run_id=self.ctx.run_id,
            agent=self.spec.name,
            step=self.step,
            started_at=self.started,
            duration_ms=int((time.perf_counter() - self.clock) * 1000),
            request=self.request,
            response=None if reply is None else reply.raw,
            tools=tools,
            error=error,
        )


def redact(value: Any, images: dict[str, str]) -> Any:
    """Store image references instead of base64 bodies."""
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            url = value["image_url"]["url"]
            return {"type": "image_url", "artifact": images.get(url, f"inline:{len(url)}")}
        return {k: redact(v, images) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, images) for v in value]
    return value


def parse_output(text: str, model: type[T]) -> tuple[T, list[str]]:
    """json-repair fixes syntax; invalid list items are dropped one by one, never re-asked."""
    data = json_repair.loads(text or "")
    if not isinstance(data, dict):
        raise AppError("Модель вернула ответ не по схеме", "model_output", 502)
    clean: dict[str, Any] = {}
    dropped: list[str] = []
    for name, info in model.model_fields.items():
        if name not in data:
            continue
        item = _list_item(info.annotation)
        if item is not None and isinstance(data[name], list):
            clean[name] = _valid_items(TypeAdapter(item), data[name], name, dropped)
        else:
            clean[name] = data[name]
    try:
        return model.model_validate(clean), dropped
    except ValidationError as exc:
        for error in exc.errors():
            dropped.append(f"{error['loc'][0]}: {error['msg']}")
            clean.pop(str(error["loc"][0]), None)
    try:
        return model.model_validate(clean), dropped
    except ValidationError as exc:
        raise AppError("Модель вернула ответ не по схеме", "model_output", 502) from exc


def _list_item(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        lists = [a for a in typing.get_args(annotation) if typing.get_origin(a) is list]
        return typing.get_args(lists[0])[0] if lists else None
    if origin is list:
        return typing.get_args(annotation)[0]
    return None


def _valid_items(adapter: TypeAdapter, items: list, name: str, dropped: list[str]) -> list:
    valid = []
    for index, item in enumerate(items):
        try:
            valid.append(adapter.validate_python(item))
        except ValidationError as exc:
            dropped.append(f"{name}[{index}]: {exc.errors()[0]['msg']}")
    return valid
