"""What agents think and do, sent to the chat as events while they work.

Observability only: prompts, decisions and the order of steps never depend on it, and an event
that fails to be written is logged and skipped, the run goes on without it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runner import AgentSpec, RunContext

logger = logging.getLogger(__name__)
Emit = Callable[..., Awaitable[None]]
Clock = Callable[[], float]
# Reasoning goes out after a pause, at a paragraph after half of it, or once the buffer is full.
PAUSE, PARAGRAPH, BUFFER = 1.0, 0.5, 2000
PREVIEW = 200


async def notify(event: Emit, type: str, message: str, status: str = "running", **data) -> None:
    """Writes an event; a failure is logged, never raised."""
    try:
        await event(type, message, status, **data)
    except Exception:
        logger.warning("Event %s was not written", type, exc_info=True)


def preview(result: dict[str, Any]) -> str:
    """A tool's answer without its images, cut short for the chat."""
    shown = {key: value for key, value in result.items() if key != "images"}
    return json.dumps(shown, ensure_ascii=False, default=str)[:PREVIEW]


class ThoughtStream:
    """One model call's reasoning in pieces, instead of a write for every token.

    A retry starts the reasoning over: the unsent text of the failed attempt is dropped, and
    the chat resets the call's text when ``attempt`` changes.
    """

    def __init__(self, event: Emit, agent: str, title: str, call: str, clock: Clock):
        self.event, self.agent, self.title, self.call, self.clock = event, agent, title, call, clock
        self.attempt, self.buffer, self.sent = 1, "", clock()

    async def __call__(self, text: str, attempt: int) -> None:
        try:
            if attempt != self.attempt:
                self.attempt, self.buffer = attempt, ""
            self.buffer += text
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
        self, spec: AgentSpec, ctx: RunContext, step: int, clock: Clock, cached: bool = False
    ):
        self.spec, self.event, self.clock, self.cached = spec, ctx.event, clock, cached
        self.id = f"{ctx.run_id}:{spec.name}:{step}"
        self.thoughts = ThoughtStream(ctx.event, spec.name, spec.title, self.id, clock)

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
