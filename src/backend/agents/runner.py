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
from .events import CallEvents, Clock, Narrate, notify, preview

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
    """Описание агента и его лимитов."""

    name: str
    title: str
    output: type[BaseModel]
    tools: tuple[str, ...] = ()
    max_steps: int = 10
    thinking: bool = True
    # лимит токенов рассуждения
    budget: int | None = None


@dataclass
class RunContext:
    """Общее состояние запуска агентов."""

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
    """Промпт агента и его версия."""
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class AgentRunner:
    def __init__(
        self,
        model: ModelClient,
        tools: ToolBox,
        uow: UowFactory,
        model_name: Callable[[], str] = lambda: "",
        clock: Clock = time.monotonic,
        narrate: Narrate | None = None,
    ):
        # модель на вызов
        self.model, self.tools, self.uow, self.model_name = model, tools, uow, model_name
        # фраза для чата
        self.clock, self.narrate = clock, narrate

    async def run(self, spec: AgentSpec, content: list[dict[str, Any]], ctx: RunContext) -> Any:
        return await self.converse(spec, [{"role": "user", "content": content}], ctx)

    async def converse(self, spec: AgentSpec, turns: list[dict[str, Any]], ctx: RunContext) -> Any:
        """Диалог агента с кешем результата."""
        key = self._key(spec, turns, ctx)
        async with self.uow() as uow:
            cached = await uow.cache.get(key)
            if cached is not None:
                await uow.traces.record(Trace(spec, ctx, 0, []).cached(key))
                await uow.commit()
        if cached is not None:
            async with CallEvents(spec, ctx, 0, self.clock, cached=True):
                return spec.output.model_validate(cached)
        output, dropped = await self._loop(spec, [self._system(spec), *turns], ctx)
        if not dropped:
            async with self.uow() as uow:
                await uow.cache.put(key, output.model_dump(mode="json"))
                await uow.commit()
        return output

    async def talk(
        self,
        spec: AgentSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        ctx: RunContext,
        step: int = 1,
    ) -> ModelReply:
        """Один текстовый ответ в чате."""
        await ctx.check()
        trace = Trace(spec, ctx, step, messages)
        async with CallEvents(spec, ctx, step, self.clock, narrate=self.narrate) as events:
            reply = await self._complete(spec, messages, tools, trace, events)
            await self._record(trace.done(reply, [], None))
        return reply

    def _key(self, spec: AgentSpec, turns: list[dict[str, Any]], ctx: RunContext) -> str:
        data = json.dumps(
            [
                "agent",
                spec.name,
                prompt(spec.name),
                spec.output.model_json_schema(),
                spec.tools,
                spec.thinking,
                spec.budget,
                self.model_name(),
                redact(turns, ctx.images),
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return "agent:" + hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def _system(spec: AgentSpec) -> dict[str, Any]:
        schema = json.dumps(spec.output.model_json_schema(), ensure_ascii=False)
        return {"role": "system", "content": prompt(spec.name) + "\n\nСхема ответа JSON\n" + schema}

    async def _loop(
        self, spec: AgentSpec, messages: list[dict[str, Any]], ctx: RunContext
    ) -> tuple[Any, list[str]]:
        seen: dict[str, dict[str, Any]] = {}
        recorded = 0
        for step in range(1, spec.max_steps + 1):
            await ctx.check()
            final = step == spec.max_steps
            schemas = [] if final else self.tools.schemas(spec.tools)
            if final and spec.tools:
                messages.append({"role": "user", "content": FINAL_STEP})
            # шаг хранит добавленное
            trace = Trace(spec, ctx, step, messages[recorded:], recorded)
            recorded = len(messages)
            async with CallEvents(spec, ctx, step, self.clock, narrate=self.narrate) as events:
                reply = await self._complete(spec, messages, schemas, trace, events)
                if not (reply.tool_calls and schemas):
                    return await self._answer(spec, reply, trace, ctx)
                executed = await self._tools(spec, reply, messages, ctx, seen, events.id)
                await self._record(trace.done(reply, executed, None))
        raise RuntimeError("The last step is offered without tools, so it always answers")

    async def _complete(
        self,
        spec: AgentSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        trace: Trace,
        events: CallEvents,
    ) -> ModelReply:
        """Вызов модели с трассировкой."""
        try:
            reply = await self.model.complete(
                messages,
                tools,
                agent=spec.name,
                thinking=spec.thinking,
                budget=spec.budget,
                on_reasoning=events.thoughts,
            )
        except AppError as exc:
            await self._record(trace.done(None, [], exc.message))
            raise
        await events.thoughts.close()
        return reply

    async def _answer(
        self, spec: AgentSpec, reply: ModelReply, trace: Trace, ctx: RunContext
    ) -> tuple[Any, list[str]]:
        await self._record(trace.done(reply, [], None))
        if reply.finish_reason == "length":
            raise AppError("Ответ модели оборван по длине", "model_truncated", 502)
        output, dropped = parse_output(reply.content, spec.output)
        if dropped:
            await ctx.event(
                "agent.dropped", f"{spec.title}, часть ответа отброшена", dropped=dropped
            )
        return output, dropped

    async def _tools(self, spec, reply, messages, ctx, seen, call_id) -> list[dict[str, Any]]:
        messages.append(
            {"role": "assistant", "content": reply.content, "tool_calls": reply.tool_calls}
        )
        executed, images = [], []
        for call in reply.tool_calls:
            name = call["function"]["name"]
            arguments = json_repair.loads(call["function"].get("arguments") or "{}")
            # повтор берёт кеш
            signature = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen[signature] = await self._call_tool(spec, name, arguments, ctx, call_id)
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

    async def _call_tool(self, spec, name, arguments, ctx, call_id) -> dict[str, Any]:
        """Вызов инструмента с превью."""
        if name not in spec.tools:
            return {"error": "Этот инструмент недоступен"}
        title = f"{spec.title}, {self.tools.title(name)}"
        await ctx.event("tool.called", title, agent=spec.name, tool=name, arguments=arguments)
        started = self.clock()
        try:
            result = await self.tools.call(name, arguments, ctx)
        except AppError as exc:
            result = {"error": exc.message}
        failed = "error" in result
        await notify(
            ctx.event,
            "tool.finished",
            f"{title}, {'ошибка' if failed else 'готово'}",
            "warning" if failed else "completed",
            agent=spec.name,
            tool=name,
            call=call_id,
            duration_ms=int((self.clock() - started) * 1000),
            result_preview=preview(result),
        )
        return result

    async def _record(self, call: AgentCall) -> None:
        async with self.uow() as uow:
            await uow.traces.record(call)
            await uow.commit()


class Trace:
    def __init__(
        self, spec: AgentSpec, ctx: RunContext, step: int, messages: list, offset: int = 0
    ):
        self.spec, self.ctx, self.step = spec, ctx, step
        self.request = {"messages": redact(messages, ctx.images), "offset": offset}
        self.started, self.clock = now(), time.perf_counter()

    def cached(self, key: str) -> AgentCall:
        """Запись об использовании кеша."""
        call = self.done(None, [], None)
        return call.model_copy(update={"request": {"cache_key": key}, "cached": True})

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
    """Замена изображений ссылками на них."""
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            url = value["image_url"]["url"]
            return {"type": "image_url", "artifact": images.get(url, f"inline:{len(url)}")}
        return {k: redact(v, images) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, images) for v in value]
    return value


def parse_output(text: str, model: type[T]) -> tuple[T, list[str]]:
    """Разбор ответа модели через json-repair."""
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
