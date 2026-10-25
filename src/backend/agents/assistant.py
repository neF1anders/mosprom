"""The assistant: one agent for the whole chat, before the work, during it and after it.

It talks on any topic and acts only through its tools: it starts a new project or updates the
current one, reads the project's journal or has the analyst work out an answer from the
journal and the agents' saved reasoning. The code reads the decision from the call and never
from the text; a call it refuses comes back to the agent as the tool's answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, Literal

from ..domain.models import Attachment, Job, Status, identifier
from ..pipeline.store import JobStore
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .chat import DOCUMENT_CHARS, called, chat_text, split_tool
from .journal import Journal
from .runner import AgentRunner, AgentSpec, RunContext, prompt
from .schemas import Output
from .sources import Sources
from .store import RunStore

logger = logging.getLogger(__name__)
REPLY, ASK, START, UPDATE = "reply", "ask_details", "start_project", "update_project"
LOG, INVESTIGATE = "project_log", "investigate"
# Steps of one turn: a look at the journal or an investigation, then the answer.
STEPS = 4
# With reasoning the model acts by its tools as reliably as when forced to, while a forced
# call switches the reasoning off; the chat shows the reasoning as it shows the agents'.
ASSISTANT = AgentSpec("assistant", "Ассистент", Output, max_steps=STEPS, budget=2000)
ANALYST = AgentSpec("analyst", "Разбор работы", Output, max_steps=1, budget=4000)
REPORTER = AgentSpec("report", "Итоговый отчёт", Output, max_steps=1, thinking=False)
# The chat the assistant reads: the latest messages, a long report cut to its start.
HISTORY = 40
MESSAGE_CHARS = 2500
REPORT_SECONDS = 60
FALLBACK = "Не получилось ответить, напишите ещё раз"
WORKING = {Status.QUEUED, Status.RUNNING}
STAGES = {
    "understanding": "разбор задания",
    "parameters": "подбор параметров",
    "validation": "проверка параметров",
    "slicing": "нарезка",
    "gcode": "проверка G-code",
    "done": "работа завершена",
}
STATES = {
    Status.DRAFT: "ещё не начат",
    Status.QUEUED: "в работе",
    Status.RUNNING: "в работе",
    Status.WAITING: "ждёт ответов на вопросы",
    Status.COMPLETED: "готов",
    Status.FAILED: "работа завершилась ошибкой",
    Status.STOPPED: "работа остановлена пользователем",
}
_TEXT = {"type": "string"}
START_ARGS = {
    "type": "object",
    "properties": {"title": _TEXT, "notes": _TEXT, "drop_current": {"type": "boolean"}},
    "required": ["title"],
}
UPDATE_ARGS = {"type": "object", "properties": {"summary": _TEXT}, "required": ["summary"]}
REPLY_ARGS = {"type": "object", "properties": {"text": _TEXT}, "required": ["text"]}
# Said once more to an agent that answers in text where its tool was due: while the
# questions wait, and when a model and a task are sent.
RECHECK_ANSWER = (
    "Ты ответил текстом, а проект ждёт ответов на вопросы. Если сообщение пользователя "
    "отвечает на них, вызови update_project, иначе повтори свой ответ"
)
RECHECK_START = (
    "Модель STL и ТЗ приложены, этого достаточно для запуска, противоречия и пробелы ТЗ "
    "найдёт проверяющий и спросит в окне вопросов. Если пользователь просит пока не "
    "запускать, повтори свой ответ, иначе начни проект через start_project"
)
INVESTIGATE_ARGS = {
    "type": "object",
    "properties": {"question": _TEXT, "say": _TEXT},
    "required": ["question"],
}
Say = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class Situation:
    """The chat and the job as the assistant sees them in one turn.

    ``new`` holds messages typed during the work that are not in the chat yet; ``files``
    the files sent that no project has taken.
    """

    job: Job
    messages: list[dict[str, Any]]
    attachments: list[Attachment]
    files: list[Attachment]
    new: list[str] = field(default_factory=list)

    @property
    def working(self) -> bool:
        return self.job.status in WORKING


@dataclass(frozen=True)
class Decision:
    """A reply in the chat, a new project or an update of the current one.

    ``text`` is what the chat shows; ``summary`` says what an update changes.
    """

    action: Literal["reply", "ask", "start", "update"]
    text: str = ""
    title: str = ""
    notes: str = ""
    summary: str = ""
    # The turn the decision came from, which the reply in the chat keeps.
    turn: str = ""


class Assistant:
    def __init__(self, runner: AgentRunner, uow: UowFactory, files: Files):
        self.runner, self.store, self.journal = runner, JobStore(uow), Journal(uow)
        self.sources = Sources(RunStore(uow), files)
        text, answer = split_tool(prompt("assistant"), REPLY, REPLY_ARGS)
        text, ask = split_tool(text, ASK, REPLY_ARGS)
        text, start = split_tool(text, START, START_ARGS)
        text, update = split_tool(text, UPDATE, UPDATE_ARGS)
        text, log = split_tool(text, LOG)
        self.system, investigate = split_tool(text, INVESTIGATE, INVESTIGATE_ARGS)
        self.reply = answer
        self.tools = [answer, ask, start, update, log, investigate]

    async def decide(self, situation: Situation, say: Say) -> Decision:
        """One turn: tools until a decision or a reply, which is a tool too or plain text;
        the last step offers only the reply.

        What the agent says along with an investigation reaches the chat at once, so the
        user sees «сейчас посмотрю» while it runs. A reply in text while the questions wait
        is checked once more, as that is how a typed answer used to get lost.
        """
        ctx = self.context(situation.job)
        await self.sources.parse(situation.files, ctx)
        messages = assistant_messages(self.system, situation)
        reminder = recheck_reason(situation)
        rechecked = reminder is None
        for step in range(1, STEPS + 1):
            offered = self.tools if step < STEPS else [self.reply]
            reply = await self.runner.talk(ASSISTANT, messages, offered, ctx, step)
            calls = reply.tool_calls
            answer = called(calls, REPLY)
            replied = answer is not None or not calls
            if replied and (rechecked or step >= STEPS - 1):
                text = str((answer or {}).get("text") or reply.content)
                return Decision("reply", chat_text(text) or FALLBACK, turn=ctx.run_id)
            if replied:
                rechecked = True
                messages += _recheck(reply.content, calls, reminder or "")
                continue
            decision = self._decision(calls, reply.content, situation)
            if decision is not None:
                return replace(decision, turn=ctx.run_id)
            spoken = str((called(calls, INVESTIGATE) or {}).get("say") or reply.content)
            if spoken.strip():
                await say(chat_text(spoken), ctx.run_id)
            messages.append({"role": "assistant", "content": reply.content, "tool_calls": calls})
            for call in calls:
                result = await self._tool(call, situation, ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise RuntimeError("The last step offers only the reply, so it always answers")

    def _decision(
        self, calls: list[dict[str, Any]], text: str, situation: Situation
    ) -> Decision | None:
        """The first decision the code accepts; a refused one is answered by ``_tool``."""
        ask = called(calls, ASK)
        if ask is not None and refusal(ASK, situation) is None:
            return Decision("ask", chat_text(str(ask.get("text") or text)) or FALLBACK)
        start = called(calls, START)
        if start is not None and refusal(START, situation, start) is None:
            title, notes = str(start.get("title") or ""), str(start.get("notes") or "")
            return Decision("start", chat_text(text), title, notes)
        update = called(calls, UPDATE)
        if update is not None and refusal(UPDATE, situation) is None:
            summary = chat_text(str(update.get("summary") or ""))
            return Decision("update", chat_text(text), summary=summary)
        return None

    async def _tool(
        self, call: dict[str, Any], situation: Situation, ctx: RunContext
    ) -> dict[str, Any]:
        name = call.get("function", {}).get("name", "")
        if name in (ASK, START, UPDATE):
            return {"error": refusal(name, situation, called([call], name) or {})}
        if name == LOG:
            return await self.journal.facts(situation.job)
        if name == INVESTIGATE:
            question = str((called([call], INVESTIGATE) or {}).get("question"))
            return {"answer": await self.investigate(situation.job, question, ctx.run_id)}
        return {"error": "Такого инструмента нет"}

    async def investigate(self, job: Job, question: str, turn: str = "") -> str:
        """The analyst reasons over the journal and the agents' reasoning; it may take a while.

        It shares the turn, so the chat opens its reasoning above the same reply.
        """
        facts = await self.journal.facts(job)
        reasoning = await self.journal.reasoning(job)
        content = (
            f"<question>\n{question}\n</question>\n\n"
            f"<facts>\n{json.dumps(facts, ensure_ascii=False)}\n</facts>\n\n"
            f"<reasoning>\n{reasoning or 'нет'}\n</reasoning>"
        )
        messages = [
            {"role": "system", "content": prompt("analyst")},
            {"role": "user", "content": content},
        ]
        reply = await self.runner.talk(ANALYST, messages, [], self.context(job, turn))
        return chat_text(reply.content) or "В журнале ответа на этот вопрос нет"

    async def report(self, job: Job) -> str:
        """The summary of a finished project; the template says the same if the model fails."""
        facts = await self.journal.facts(job)
        messages = [
            {"role": "system", "content": prompt("report")},
            {
                "role": "user",
                "content": f"<facts>\n{json.dumps(facts, ensure_ascii=False)}\n</facts>",
            },
        ]
        try:
            reply = await asyncio.wait_for(
                self.runner.talk(REPORTER, messages, [], self.context(job)), REPORT_SECONDS
            )
            text = chat_text(reply.content)
        except Exception:
            # The project is done whatever the model says; the template reports it then.
            logger.warning("The report of job %s fell back to the template", job.id, exc_info=True)
            text = ""
        return text or template(facts)

    def context(self, job: Job, turn: str = "") -> RunContext:
        """The chat is never cancelled by a newer revision: the caller checks it on apply."""
        return RunContext(
            job_id=job.id,
            revision=job.revision,
            run_id=turn or identifier(),
            check=_nothing,
            event=partial(self.store.event, job.id, job.revision),
        )


async def _nothing() -> None:
    return None


def refusal(name: str, situation: Situation, arguments: dict[str, Any] | None = None) -> str | None:
    """Why the code does not take the call, said to the agent; None when it does."""
    job = situation.job
    if name == ASK and asked(situation):
        return (
            "Подробности ты уже спрашивал, второй раз не спрашивай. Если среди новых файлов "
            "есть модель STL, начни проект, иначе ответь через reply"
        )
    if name == ASK and described(situation):
        return RECHECK_START
    waiting = job.status == Status.WAITING and job.card is not None
    if name == START and waiting and not (arguments or {}).get("drop_current"):
        return (
            "Текущий проект ждёт ответов на вопросы. Спроси пользователя, отложить ли его, и "
            "начни новый с drop_current true, только когда он согласится"
        )
    if name == START and situation.working:
        return (
            "Сейчас идёт работа над текущим проектом, новый можно начать, когда она закончится. "
            "Скажи об этом пользователю"
        )
    if name == START and not any(a.kind == "stl" for a in situation.files):
        return "Среди новых файлов нет модели STL. Попроси пользователя приложить её"
    if name == UPDATE and job.revision == 0:
        return "Проекта ещё нет. Если есть модель STL, начни новый проект через start_project"
    return None


def asked(situation: Situation) -> bool:
    """The details of this part were asked already: since the current project began, or in
    the whole chat before the first one."""
    project = situation.job.project
    since = project.first_message if project else 0
    return any(m.get("kind") == "gate" and m.get("seq", 0) >= since for m in situation.messages)


def described(situation: Situation) -> bool:
    """A model and a task are sent: enough to start, the checker asks what is missing."""
    kinds = {a.kind == "stl" for a in situation.files}
    return kinds == {True, False}


def recheck_reason(situation: Situation) -> str | None:
    """Why a reply in text gets one more look: the questions wait or a task is sent."""
    if open_questions(situation.job):
        return RECHECK_ANSWER
    if described(situation) and not situation.working:
        return RECHECK_START
    return None


def open_questions(job: Job) -> list[str]:
    if job.card is None or job.status != Status.WAITING:
        return []
    return [q.title for q in job.card.questions if not q.answer]


def _recheck(content: str, calls: list[dict[str, Any]], reminder: str) -> list[dict[str, Any]]:
    """The reply goes back to the agent with the reminder, as a tool answer or a user turn."""
    if not calls:
        return [
            {"role": "assistant", "content": content},
            {"role": "user", "content": reminder},
        ]
    return [
        {"role": "assistant", "content": content, "tool_calls": calls},
        *({"role": "tool", "tool_call_id": c.get("id", ""), "content": reminder} for c in calls),
    ]


def assistant_messages(system: str, situation: Situation) -> list[dict[str, Any]]:
    """The chat as a dialog; the last user turn carries the state and the new documents."""
    names = {a.id: a.filename for a in situation.attachments}
    turns: list[dict[str, Any]] = []
    for message in situation.messages[-HISTORY:]:
        text = _shown(message, names)
        if turns and turns[-1]["role"] == message["role"]:
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": message["role"], "content": text})
    if situation.new and turns and turns[-1]["role"] == "user":
        turns[-1]["content"] += "\n\n" + "\n\n".join(situation.new)
    elif situation.new:
        turns.append({"role": "user", "content": "\n\n".join(situation.new)})
    if not turns or turns[-1]["role"] != "user":
        turns.append({"role": "user", "content": "Пользователь ничего не написал"})
    turns[-1]["content"] = (
        f"<state>\n{json.dumps(state(situation), ensure_ascii=False)}\n</state>\n\n"
        f"<documents>\n{new_documents(situation.files) or 'нет'}\n</documents>\n\n"
        + turns[-1]["content"]
    )
    return [{"role": "system", "content": system}, *turns]


def _shown(message: dict[str, Any], names: dict[str, str]) -> str:
    text = str(message.get("text") or "")
    if len(text) > MESSAGE_CHARS:
        text = text[:MESSAGE_CHARS] + " …"
    files = [names[i] for i in message.get("attachment_ids") or [] if i in names]
    return text + (f"\n[вложения {', '.join(files)}]" if files else "")


def state(situation: Situation) -> dict[str, Any]:
    job = situation.job
    project = job.project
    current: dict[str, Any] | str = "нет"
    if project is not None or job.card is not None:
        current = {
            "название": project.title if project else job.title,
            "состояние": STATES.get(job.status, job.status.value),
            "назначение": job.card.purpose if job.card else "",
        }
    waiting = open_questions(job)
    state = {
        "работа": f"идёт, этап {STAGES[job.stage]}" if situation.working else "не идёт",
        "текущий проект": current,
        "вопросы без ответа": waiting,
        "новые файлы": [_file(a) for a in situation.files],
    }
    if waiting:
        state["как принять ответ"] = (
            "любой ответ на эти вопросы, даже «не знаю» или «решай сам», передай вызовом "
            "update_project, текстом он не засчитывается и работа стоит"
        )
    return state


def _file(attachment: Attachment) -> str:
    kind = "модель STL" if attachment.kind == "stl" else "документ"
    return f"{attachment.filename} ({kind})"


def new_documents(files: list[Attachment]) -> str:
    parts = []
    for attachment in files:
        text = "\n".join(str(f.get("text") or "") for f in attachment.fragments).strip()
        if text:
            parts.append(f"{attachment.filename}\n{text[:DOCUMENT_CHARS]}")
    return "\n\n".join(parts)


def template(facts: dict[str, Any]) -> str:
    """The report without the model, from the same facts."""
    lines = [_headline(facts)]
    sections = [
        ("Что я взял из ваших файлов", facts.get("requirements", [])[:8]),
        ("Ваши ответы", [f"{q['question']} {q['answer']}" for q in facts.get("questions", [])]),
        ("Допущения", [a["text"] for a in facts.get("assumptions", [])]),
        (
            "Вопросы, которые я не стал задавать",
            [f"{w['question']} {w['reason']}" for w in facts.get("waived_questions", [])],
        ),
        ("Параметры печати", _parameter_lines(facts.get("parameters") or {})),
        ("Результат", _result_lines(facts.get("slicing") or {})),
    ]
    for title, items in sections:
        if items:
            lines += ["", f"### {title}", *[f"- {item}" for item in items]]
    lines += [
        "",
        "Можно спросить, почему я что-то решил, поправить задание или прислать новую деталь",
    ]
    return chat_text("\n".join(lines))


HEADLINES = {
    "ready": "Проект готов, параметры и G-code прошли проверку",
    "not_sliced": "Параметры подобраны, но проект не создан",
    "parameters_attention": "Параметры подобраны, но требуют внимания",
    "attention": "Проект создан, но кое-что требует внимания",
}


def _headline(facts: dict[str, Any]) -> str:
    """The outcome first; a selection that found nothing says so, whatever was sliced."""
    if (facts.get("parameters") or {}).get("status") == "infeasible":
        return "Подобрать параметры под все требования не получилось"
    return HEADLINES.get(str(facts.get("outcome")), "Работа завершена")


def _parameter_lines(parameters: dict[str, Any]) -> list[str]:
    if not parameters:
        return []
    materials = ", ".join(str(m.get("id")) for m in parameters.get("materials", []))
    lines = [
        f"Режим {parameters.get('mode')}, профиль {parameters.get('quality')}, материал {materials}"
    ]
    lines += [f"Не выполнено {why}" for why in parameters.get("unsatisfied", [])]
    return lines


def _result_lines(slicing: dict[str, Any]) -> list[str]:
    if not slicing:
        return []
    lines = [str(slicing.get("message") or "")]
    seconds = slicing.get("print_time_seconds")
    if seconds:
        hours, minutes = divmod(round(seconds / 60), 60)
        lines.append(f"Печать {hours} ч {minutes} мин" if hours else f"Печать {minutes} мин")
    if slicing.get("folder"):
        lines.append(f"Проект лежит в папке {slicing['folder']}")
    return [line for line in lines if line]
