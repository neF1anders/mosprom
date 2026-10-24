"""Stage one: the gate in the chat, then one interpreter and one checker over files read by code.

Every chat message reaches the gate first; it talks, asks for details once, or starts the work
by calling its tool. The interpreter reads all sources while the code analyses the STL, then
the checker edits the draft and asks its questions in one go. The answers return to the same
checker dialog, so nothing before it runs again, and so does a correction queued meanwhile.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from functools import partial
from typing import Any

from pydantic import BaseModel, Field

from ..domain.errors import AppError, OperationCancelled
from ..domain.hashing import digest
from ..domain.models import (
    Attachment,
    Job,
    Question,
    Source,
    SourceFile,
    Status,
    TaskCard,
    identifier,
)
from ..domain.requirement_keys import RequirementKeys
from ..domain.rules import RULES_VERSION, UNKNOWN_ANSWER, assess
from ..domain.transitions import transition
from ..pipeline.store import SafePoint, no_safe_point
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .card import WorkingCard, fill, merged, stable_references, summary, to_question
from .context import ContentBuilder, Inputs, codes_block, collect, follow_up
from .gate import clean, gate_messages, split_tool, started
from .runner import AgentRunner, AgentSpec, RunContext, prompt, redact
from .schemas import Output, Review, draft_with_codes
from .sources import ANALYZER_VERSION, Sources, StlFacts
from .store import RunStore

READING = ("view_page", "convert_units")
# Budgets sit near the 90th percentile of traced reasoning: they cut runaway tails only.
GATE = AgentSpec("gate", "Ассистент", Output, max_steps=1, thinking=False)
CHECKER = AgentSpec("checker", "Проверка карточки", Review, max_steps=1, budget=6000)
PROMPTS = ("gate", "interpreter", "checker")
# How often a running stage checks for a stop or a newer revision, even mid model call.
CHECK_SECONDS = 2
OFF_TOPIC = (
    "Я помогаю подготовить задание на 3D печать. Приложите STL модель и ТЗ или опишите деталь"
)
FOLLOW_UP = "Ответы пользователя на твои вопросы и карточка после твоей правки, id прежние"
CORRECTION = "Правка пользователя и текущая карточка, id прежние, новых вопросов не задавай"


@dataclass(frozen=True)
class Stage1Settings:
    timeout_seconds: float = 900
    job_images: int = 150


class Session(BaseModel):
    """What the answer turn continues: the checker's first turn, its reply and the card.

    ``history`` holds the turns taken since, so a later correction goes on from the last.
    """

    turn: list[dict[str, Any]]
    review: dict[str, Any]
    card: WorkingCard
    asked: list[str]
    history: list[dict[str, Any]] = Field(default_factory=list)


def session_key(job_id: str, revision: int) -> str:
    return f"stage1:review:{job_id}:{revision}"


def correction_key(job_id: str, revision: int) -> str:
    """Every card can take a correction; the answers keep their own key and routing."""
    return f"stage1:correction:{job_id}:{revision}"


class Stage1:
    def __init__(
        self,
        uow: UowFactory,
        files: Files,
        runner: AgentRunner,
        settings: Stage1Settings,
        codes: RequirementKeys,
        *,
        safe_point: SafePoint = no_safe_point,
    ):
        self.store, self.files, self.runner, self.settings = RunStore(uow), files, runner, settings
        self.safe_point = safe_point
        self.sources, self.keys, self.codes = Sources(self.store, files), codes, codes_block(codes)
        self.interpreter = AgentSpec(
            "interpreter", "Разбор задания", draft_with_codes(codes), READING, budget=9000
        )
        self.gate_prompt, self.start = split_tool(prompt("gate"))

    async def run(
        self, job_id: str, revision: int, start: bool = False, correction: bool = False
    ) -> None:
        """``start`` resumes work the user stopped or that failed, without asking the gate;
        ``correction`` takes in a queued message the agent «Корректировка» found to change
        the task."""
        ctx = RunContext(
            job_id=job_id,
            revision=revision,
            run_id=identifier(),
            check=partial(self.store.check, job_id, revision),
            event=partial(self.store.event, job_id, revision),
        )
        try:
            await asyncio.wait_for(
                self._guarded(ctx, start, correction), self.settings.timeout_seconds
            )
        except OperationCancelled:
            await self.store.cancel(job_id)
        except TimeoutError:
            await self.store.fail(
                ctx.job_id, ctx.revision, "Обработка заняла слишком много времени", "stage1_timeout"
            )
        except AppError as exc:
            await self.store.fail(ctx.job_id, ctx.revision, exc.message, exc.code)
        except Exception:
            # A bug must not leave the job running forever; the queue still records the failure.
            await self.store.fail(
                ctx.job_id,
                ctx.revision,
                "Внутренняя ошибка обработки, попробуйте ещё раз",
                "internal",
            )
            raise

    async def _guarded(self, ctx: RunContext, start: bool, correction: bool) -> None:
        """A stop or a newer revision interrupts the run at once, even inside a model call."""
        work = asyncio.ensure_future(self._run(ctx, start, correction))
        try:
            while not work.done():
                await asyncio.wait({work}, timeout=CHECK_SECONDS)
                if not work.done():
                    await ctx.check()
        except BaseException:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise
        work.result()

    async def _run(self, ctx: RunContext, start: bool, correction: bool) -> None:
        job = await self.store.update(ctx.job_id, ctx.revision, _started)
        attachments = _active(job, await self.store.attachments(job.id))
        messages = await self.store.messages(job.id)
        await self.sources.parse(attachments, ctx)
        inputs = collect(messages, attachments, job.answers, None)
        if inputs.images() > self.settings.job_images:
            raise AppError(
                f"В задании больше {self.settings.job_images} страниц и изображений, "
                "уберите лишние файлы",
                "too_many_pages",
                413,
            )
        ctx.sources.update(inputs.sources())
        content = ContentBuilder(self.files, inputs, ctx, await self.store.knowledge(), self.codes)
        session = await self._session(job, attachments, correction)
        # A correction is not left to the gate, which could answer and drop the card.
        direct = start or (correction and _with_stl(attachments))
        if session is not None:
            await self._answered(
                job, attachments, messages, inputs, session, content, ctx, correction
            )
        elif direct or await self._gate(job, attachments, messages, inputs, ctx):
            await self._work(job, attachments, content, ctx)
        await self.safe_point(ctx.job_id, ctx.revision)

    async def _session(
        self, job: Job, attachments: list[Attachment], correction: bool
    ) -> Session | None:
        """The checker's dialog goes on while the files stay the same: for the answers while
        its card asks, for a correction whatever the card."""
        card = job.card
        if card is None or _card_files(card) != {a.id for a in attachments}:
            return None
        if not (correction or card.questions):
            return None
        key = correction_key if correction else session_key
        stored = await self.store.cached(key(job.id, card.revision))
        return Session.model_validate(stored) if stored is not None else None

    async def _gate(
        self,
        job: Job,
        attachments: list[Attachment],
        messages: list[dict[str, Any]],
        inputs: Inputs,
        ctx: RunContext,
    ) -> bool:
        """True to start the work; otherwise the gate's reply goes to the chat.

        The gate may ask for details only once: after its request, the next message with a
        model starts the work whatever it says.
        """
        stl = next((a.filename for a in attachments if a.id == job.active_stl), None)
        last = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
        if stl and last is not None and last.get("kind") == "gate":
            return True
        reply = await self.runner.talk(
            GATE,
            gate_messages(self.gate_prompt, messages, inputs, stl),
            [self.start] if stl else [],
            ctx,
        )
        if stl and started(reply.tool_calls):
            return True
        current = _card_files(job.card) == {a.id for a in attachments}
        # Only a reply before the first card for these files asks for details.
        kind = "gate" if stl and not current else "chat"
        await self.store.reply(ctx, clean(reply.content) or OFF_TOPIC, kind, current)
        return False

    async def _work(
        self, job: Job, attachments: list[Attachment], content: ContentBuilder, ctx: RunContext
    ) -> None:
        await self.store.begin(ctx)
        await self.sources.announce(attachments, ctx)
        await ctx.event("interpretation.started", "Разбираю задание")
        # The interpreter does not need the STL; its analysis runs meanwhile.
        stl = asyncio.ensure_future(self.sources.stl(job, attachments, ctx))
        try:
            # Earlier answers are facts of the task, so a new run starts from them.
            draft = await self.runner.run(
                self.interpreter, await content.build(stl=False, codes=True), ctx
            )
            facts = await stl
        finally:
            # Settled either way, so a failure of the analysis is never left unretrieved.
            stl.cancel()
            await asyncio.gather(stl, return_exceptions=True)
        working = WorkingCard.from_draft(draft, self.keys)
        found = len(working.codes) + len(working.requirements)
        await ctx.event("interpretation.completed", f"Найдено требований {found}", "completed")
        card = self._card(job, attachments, facts)
        await ctx.event("checking.started", "Проверяю карточку")
        if facts is not None:
            ctx.stl_report = facts.report
            content.use_geometry(facts.geometry)
        turn = await content.build(
            stl=False, report=True, knowledge=True, codes=True, card=working.view()
        )
        review = await self.runner.run(CHECKER, turn, ctx)
        working.apply(review, self.keys)
        card.questions = merged([to_question(q) for q in review.questions], {})
        session = Session(
            turn=redact(turn, ctx.images),
            review=review.model_dump(mode="json"),
            card=working,
            asked=[q.id for q in card.questions],
        ).model_dump(mode="json")
        if card.questions:
            await self.store.cache(session_key(job.id, ctx.revision), session)
        # Any card can take a correction later, which goes on in this same dialog.
        await self.store.cache(correction_key(job.id, ctx.revision), session)
        asked = len(card.questions)
        await ctx.event(
            "checking.completed",
            f"Нужны ответы на вопросы, всего {asked}" if asked else "Карточка проверена",
            "completed",
        )
        await self._finish(card, working, attachments, ctx)

    async def _answered(
        self,
        job: Job,
        attachments: list[Attachment],
        messages: list[dict[str, Any]],
        inputs: Inputs,
        session: Session,
        content: ContentBuilder,
        ctx: RunContext,
        correction: bool = False,
    ) -> None:
        """The answers continue the checker's dialog; nothing before it runs again.

        A second round of questions is not asked: whatever the checker still wants to know
        is passed on as unknown. A correction is one more turn of the same dialog.
        """
        assert job.card is not None
        previous = job.card
        await self.store.begin(ctx)
        await ctx.event("files.completed", "Файлы прочитаны", "completed")
        if previous.stl_analysis is not None:
            await ctx.event("stl.completed", "STL проанализирован", "completed")
        await ctx.event("interpretation.completed", "Задание разобрано", "completed")
        await ctx.event("checking.started", "Учитываю правку" if correction else "Учитываю ответы")
        # A correction brings only what the user typed: the answers are in the dialog already.
        asked = [] if correction else [q for q in previous.questions if q.id in session.asked]
        replies = _replies(asked, values(job), messages, inputs, previous.revision)
        ctx.sources.update({reply.id: reply for reply in replies})
        intro = CORRECTION if correction else FOLLOW_UP
        turn = {"role": "user", "content": follow_up(intro, replies, session.card.view())}
        dialog: list[dict[str, Any]] = [
            {"role": "user", "content": await content.restore(session.turn)},
            {"role": "assistant", "content": json.dumps(session.review, ensure_ascii=False)},
            *session.history,
            turn,
        ]
        review = await self.runner.converse(CHECKER, dialog, ctx)
        working = session.card
        working.apply(review, self.keys)
        working.unknowns += [q.title for q in review.questions]
        # The new card can take a correction too, which goes on from the turn just taken.
        answer = json.dumps(review.model_dump(mode="json"), ensure_ascii=False)
        history = [*session.history, turn, {"role": "assistant", "content": answer}]
        continued = session.model_copy(update={"card": working, "history": history})
        await self.store.cache(
            correction_key(job.id, ctx.revision), continued.model_dump(mode="json")
        )
        card = previous.model_copy(deep=True, update={"revision": ctx.revision})
        # Answered or not, the questions no longer hold the card back.
        kept = previous.questions if correction else asked
        card.questions = merged(
            [q.model_copy(update={"blocking": False}) for q in kept], values(job)
        )
        done = "Правка учтена" if correction else "Ответы учтены"
        await ctx.event("checking.completed", done, "completed")
        await self._finish(card, working, attachments, ctx)

    async def _finish(
        self, card: TaskCard, working: WorkingCard, attachments: list[Attachment], ctx: RunContext
    ) -> None:
        fill(card, working, working.requirements_for(self.keys, ctx))
        card.versions.update(
            {f"prompt.{name}": digest(prompt(name)) for name in PROMPTS},
            requirement_keys=self.keys.version,
            model=self.runner.model_name(),
        )
        stable_references(card, ctx)
        await self.store.finish(ctx, assess(card, failed(attachments)), summary(card))

    def _card(self, job: Job, attachments: list[Attachment], stl: StlFacts | None) -> TaskCard:
        return TaskCard(
            job_id=job.id,
            revision=job.revision,
            geometry=stl.geometry if stl else None,
            stl_analysis=stl.analysis if stl else None,
            files=[
                SourceFile(id=a.id, filename=a.filename, kind=a.kind, sha256=a.sha256)
                for a in attachments
            ],
            versions={"rules": RULES_VERSION, "analyzer": ANALYZER_VERSION},
        )


def _replies(
    asked: list[Question],
    answers: dict[str, str],
    messages: list[dict[str, Any]],
    inputs: Inputs,
    revision: int,
) -> list[Source]:
    """Answers from the question window, then anything the user typed instead."""
    replies = [
        Source(
            id=f"a:{q.id}",
            ref=f"answer:{q.id}",
            kind="answer",
            text=f"{q.title} {answers.get(q.id, UNKNOWN_ANSWER)}",
        )
        for q in asked
    ]
    typed = {m["id"] for m in messages if m["role"] == "user" and m["revision"] > revision}
    return replies + [m for m in inputs.messages if m.ref in typed]


def values(job: Job) -> dict[str, str]:
    return {key: answer.value for key, answer in job.answers.items()}


def failed(attachments: list[Attachment]) -> list[str]:
    return [a.filename for a in attachments if a.status == "failed"]


def _started(job: Job) -> None:
    job.status = transition(job.status, Status.RUNNING)


def _active(job: Job, attachments: list[Attachment]) -> list[Attachment]:
    return [
        a
        for a in attachments
        if a.active and not a.draft and (a.kind != "stl" or a.id == job.active_stl)
    ]


def _with_stl(attachments: list[Attachment]) -> bool:
    return any(a.kind == "stl" for a in attachments)


def _card_files(card: TaskCard | None) -> set[str]:
    return {f.id for f in card.files} if card else set()
