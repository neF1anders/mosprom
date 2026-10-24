"""The agent «Корректировка»: a message queued while the job works changes the task or not.

Like the gate, it decides only by calling its tool, so the code reads the decision from the
call and never from the text. Without the call its text is the reply in the chat, and the
work goes on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from typing import Any

from ..domain.models import Job, identifier
from ..pipeline.store import JobStore
from ..ports.persistence import UowFactory
from .gate import called, clean, split_tool
from .runner import AgentRunner, AgentSpec, RunContext, prompt
from .schemas import Output

STEER = AgentSpec("steer", "Корректировка", Output, max_steps=1, thinking=False)
APPLY = "apply_correction"
SUMMARY = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}
# Enough of the card to tell a correction from small talk and to name what it changes.
REQUIREMENTS = 20
STAGES = {
    "understanding": "разбор задания",
    "parameters": "подбор параметров",
    "validation": "проверка параметров",
    "slicing": "нарезка",
    "gcode": "проверка G-code",
    "done": "работа завершена",
}
APPLIED = "Учитываю правку и разбираю задание заново"
REPLY = "Задание от этого не меняется, продолжаю работу"


@dataclass(frozen=True)
class Decision:
    """A correction with the line the timeline shows for it, or a reply in the chat."""

    correction: bool
    text: str


class Steer:
    def __init__(self, runner: AgentRunner, uow: UowFactory):
        self.runner, self.store = runner, JobStore(uow)
        self.system, self.tool = split_tool(prompt("steer"), APPLY, SUMMARY)

    async def decide(self, job: Job, texts: list[str]) -> Decision:
        """A call with a text is still a correction: the call is the decision."""
        ctx = RunContext(
            job_id=job.id,
            revision=job.revision,
            run_id=identifier(),
            check=partial(self.store.check, job.id, job.revision),
            event=partial(self.store.event, job.id, job.revision),
        )
        messages = steer_messages(self.system, job, texts)
        reply = await self.runner.talk(STEER, messages, [self.tool], ctx)
        arguments = called(reply.tool_calls, APPLY)
        if arguments is not None:
            return Decision(True, clean(str(arguments.get("summary") or "")) or APPLIED)
        return Decision(False, clean(reply.content) or REPLY)


def steer_messages(system: str, job: Job, texts: list[str]) -> list[dict[str, Any]]:
    """Where the work stands and what the card says, then the queued messages as data."""
    card = job.card
    requirements = card.requirements[:REQUIREMENTS] if card else []
    state = {
        "этап": STAGES[job.stage],
        "назначение": card.purpose if card else "",
        "требования": [
            " ".join(part for part in (r.label or r.key, r.value, r.unit) if part)
            for r in requirements
        ],
    }
    messages = "\n\n".join(texts)
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"<state>\n{json.dumps(state, ensure_ascii=False)}\n</state>\n\n"
            f"<messages>\n{messages}\n</messages>",
        },
    ]
