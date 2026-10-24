"""What agents think and do, sent to the chat as events while they work.

Observability only: prompts, decisions and the order of steps never depend on it, and an event
that fails to be written is logged and skipped, the run goes on without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..ports.operations import ModelClient
    from .runner import AgentSpec, RunContext

logger = logging.getLogger(__name__)
Emit = Callable[..., Awaitable[None]]
Clock = Callable[[], float]
# The agent's title, the fresh part of its reasoning and the phrase said before.
Narrate = Callable[[str, str, str], Awaitable[str]]
# Reasoning goes out after a pause, at a paragraph after half of it, or once the buffer is full.
PAUSE, PARAGRAPH, BUFFER = 1.0, 0.5, 2000
PREVIEW = 200
# The narrator speaks a little after a call starts, then whenever the reasoning has moved on.
NARRATION_FIRST, NARRATION_EVERY, NARRATION_WINDOW, NARRATION_SECONDS = 3.0, 7.0, 1000, 15
# Phrases are written by tasks of their own; the set keeps them alive until they stop.
_background: set[asyncio.Task] = set()
NARRATION = (
    "Ты показываешь пользователю, чем сейчас занят агент «{title}», который готовит задание "
    "на 3D печать. Тебе дан свежий фрагмент его черновых рассуждений, обычно на английском. "
    "Напиши одну короткую фразу по-русски от первого лица в настоящем времени о том, что агент "
    "делает прямо сейчас, например «Сверяю момент из ТЗ с нагрузкой на зуб». Не больше "
    "двенадцати слов, без тире и двоеточий, без точки в конце, без выдумок сверх фрагмента. "
    "Пиши о детали и задании, а не о внутренней кухне, без слов вроде JSON, схема, поле, "
    "инструмент. Прошлая фраза была «{previous}», не повторяй её."
)


async def notify(event: Emit, type: str, message: str, status: str = "running", **data) -> None:
    """Writes an event; a failure is logged, never raised."""
    try:
        await event(type, message, status, **data)
    except Exception:
        logger.warning("Event %s was not written", type, exc_info=True)


class Narrator:
    """Says in Russian what an agent is doing, from the fresh part of its reasoning.

    The model reasons in English whatever its prompt asks, so the chat shows a short phrase
    and keeps the reasoning itself a click away. The agent never sees the phrase.
    """

    def __init__(self, model: ModelClient):
        self.model = model

    async def __call__(self, title: str, reasoning: str, previous: str) -> str:
        system = NARRATION.format(title=title, previous=previous or "нет")
        reply = await self.model.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": reasoning}],
            [],
            agent="narrator",
            thinking=False,
        )
        return reply.content.strip().strip('«»"').rstrip(".")


class Narration:
    """The narrator's phrases for one model call, written while the call goes on.

    It never holds the call up: the phrases come from a task of their own, a failed one is
    skipped, and the task stops with the call.
    """

    def __init__(
        self,
        event: Emit,
        agent: str,
        call: str,
        title: str,
        narrate: Narrate,
        first: float = NARRATION_FIRST,
        every: float = NARRATION_EVERY,
    ):
        self.event, self.agent, self.call, self.title = event, agent, call, title
        self.narrate, self.first, self.every = narrate, first, every
        self.text, self.attempt = "", 1
        self.task: asyncio.Task | None = None

    def feed(self, text: str, attempt: int) -> None:
        if attempt != self.attempt:
            self.attempt, self.text = attempt, ""
        self.text += text
        if self.task is None:
            self.task = asyncio.create_task(self._speak())
            _background.add(self.task)
            self.task.add_done_callback(_background.discard)

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def _speak(self) -> None:
        previous, seen, delay = "", 0, self.first
        while True:
            await asyncio.sleep(delay)
            delay = self.every
            if len(self.text) == seen:
                continue
            seen, attempt = len(self.text), self.attempt
            phrase = await self._phrase(self.text[-NARRATION_WINDOW:], previous)
            if phrase and phrase != previous:
                previous = phrase
                await notify(
                    self.event,
                    "agent.narration",
                    phrase,
                    agent=self.agent,
                    call=self.call,
                    attempt=attempt,
                    text=phrase,
                )

    async def _phrase(self, reasoning: str, previous: str) -> str:
        try:
            return await asyncio.wait_for(
                self.narrate(self.title, reasoning, previous), NARRATION_SECONDS
            )
        except Exception:
            logger.warning("No narration for %s", self.call, exc_info=True)
            return ""


def preview(result: dict[str, Any]) -> str:
    """A tool's answer without its images, cut short for the chat."""
    shown = {key: value for key, value in result.items() if key != "images"}
    return json.dumps(shown, ensure_ascii=False, default=str)[:PREVIEW]


class ThoughtStream:
    """One model call's reasoning in pieces, instead of a write for every token.

    A retry starts the reasoning over: the unsent text of the failed attempt is dropped, and
    the chat resets the call's text when ``attempt`` changes.
    """

    def __init__(
        self,
        event: Emit,
        agent: str,
        title: str,
        call: str,
        clock: Clock,
        narration: Narration | None = None,
    ):
        self.event, self.agent, self.title, self.call, self.clock = event, agent, title, call, clock
        self.attempt, self.buffer, self.sent = 1, "", clock()
        self.narration = narration

    async def __call__(self, text: str, attempt: int) -> None:
        try:
            if attempt != self.attempt:
                self.attempt, self.buffer = attempt, ""
            self.buffer += text
            if self.narration is not None:
                self.narration.feed(text, attempt)
            await self._send(self._ready())
        except Exception:
            logger.warning("Reasoning of %s was not sent", self.call, exc_info=True)

    async def close(self) -> None:
        """What is left goes out once the call has ended."""
        await self._send(len(self.buffer))

    def _ready(self) -> int:
        """How much of the buffer goes out now: all of it, up to a paragraph, or nothing."""
        elapsed = self.clock() - self.sent
        if elapsed >= PAUSE or len(self.buffer) >= BUFFER:
            return len(self.buffer)
        end = self.buffer.rfind("\n\n")
        return end + 2 if elapsed >= PARAGRAPH and end >= 0 else 0

    async def _send(self, size: int) -> None:
        if not size:
            return
        text, self.buffer = self.buffer[:size], self.buffer[size:]
        self.sent = self.clock()
        await notify(
            self.event,
            "agent.thinking",
            f"{self.title}, рассуждает",
            agent=self.agent,
            call=self.call,
            attempt=self.attempt,
            text=text,
        )


class CallEvents:
    """Started and finished around one call of an agent, with its reasoning in between.

    The call id names the run, the agent and the step, like the call's row in the journal; a
    reused result is step 0. A cancelled call sends nothing more, the stop has its own event.
    """

    def __init__(
        self,
        spec: AgentSpec,
        ctx: RunContext,
        step: int,
        clock: Clock,
        cached: bool = False,
        narrate: Narrate | None = None,
    ):
        self.spec, self.event, self.clock, self.cached = spec, ctx.event, clock, cached
        self.id = f"{ctx.run_id}:{spec.name}:{step}"
        self.narration = (
            None
            if narrate is None
            else Narration(ctx.event, spec.name, self.id, spec.title, narrate)
        )
        self.thoughts = ThoughtStream(
            ctx.event, spec.name, spec.title, self.id, clock, self.narration
        )

    async def __aenter__(self) -> CallEvents:
        self.started = self.clock()
        await notify(
            self.event,
            "agent.started",
            f"{self.spec.title}, работает",
            agent=self.spec.name,
            title=self.spec.title,
            call=self.id,
        )
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # The narrator stops with the call, a cancelled one included.
        if self.narration is not None:
            self.narration.stop()
        if kind is not None and not issubclass(kind, Exception):
            return
        await self.thoughts.close()
        outcome = "ответ из кеша" if self.cached else "готово"
        await notify(
            self.event,
            "agent.finished",
            f"{self.spec.title}, {'ошибка' if error else outcome}",
            "failed" if error else "completed",
            agent=self.spec.name,
            title=self.spec.title,
            call=self.id,
            duration_ms=int((self.clock() - self.started) * 1000),
            cached=self.cached,
        )
