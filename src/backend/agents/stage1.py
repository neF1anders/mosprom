"""Stage one: one interpreter and one checker over files read by code.

The assistant in the chat starts the work by its tool. The interpreter reads the sources of
the current project while the code analyses the STL, then the checker edits the draft and
asks its questions in one go. The answers return to the same checker dialog, so nothing
before it runs again, and so does a correction.
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
from ..domain.projects import earlier_answers, in_project, project_messages
from ..domain.requirement_keys import RequirementKeys
from ..domain.rules import RULES_VERSION, UNKNOWN_ANSWER, assess
from ..domain.transitions import transition
from ..pipeline.store import SafePoint, no_safe_point
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .card import (
    WorkingCard,
    fill,
    merged,
    settle_questions,
    stable_references,
    summary,
    to_question,
)
from .context import ContentBuilder, Inputs, codes_block, collect, follow_up
from .runner import AgentRunner, AgentSpec, RunContext, prompt, redact
from .schemas import Review, draft_with_codes
from .sources import ANALYZER_VERSION, Sources, StlFacts
from .store import RunStore

READING = ("view_page", "convert_units")
# Budgets sit near the 90th percentile of traced reasoning: they cut runaway tails only.
CHECKER = AgentSpec("checker", "Проверка карточки", Review, max_steps=1, budget=6000)
PROMPTS = ("interpreter", "checker")
# How often a running stage checks for a stop or a newer revision, even mid model call.
CHECK_SECONDS = 2
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

    async def run(
        self,
        job_id: str,
        revision: int,
        start: bool = False,
        correction: bool = False,
        typed: list[str] | None = None,
    ) -> None:
        """``start`` runs the whole stage anew; ``correction`` continues the checker's dialog
        with what the user typed; ``typed`` are messages already in the chat that answer the
        open questions or carry the correction."""
        ctx = RunContext(
            job_id=job_id,
            revision=revision,
            run_id=identifier(),
            check=partial(self.store.check, job_id, revision),
            event=partial(self.store.event, job_id, revision),
        )
        try:
            await asyncio.wait_for(
                self._guarded(ctx, start, correction, typed or []), self.settings.timeout_seconds
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

    async def _guarded(
        self, ctx: RunContext, start: bool, correction: bool, typed: list[str]
    ) -> None:
        """A stop or a newer revision interrupts the run at once, even inside a model call."""
        work = asyncio.ensure_future(self._run(ctx, start, correction, typed))
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

    async def _run(self, ctx: RunContext, start: bool, correction: bool, typed: list[str]) -> None:
        job = await self.store.update(ctx.job_id, ctx.revision, _started)
        attachments = _active(job, await self.store.attachments(job.id))
        messages = with_notes(job, project_messages(job, await self.store.messages(job.id)))
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
        session = None if start else await self._session(job, attachments, correction)
        if session is not None:
            await self._answered(
                job, attachments, messages, inputs, session, content, ctx, correction, typed
            )
        else:
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
        earlier = [f"{title} {value}" for title, value in earlier_answers(job).items()]
        # Only a chat with earlier parts adds the block, so the usual input stays as it was.
        extra: dict[str, Any] = {"earlier_answers": earlier} if earlier else {}
        turn = await content.build(
            stl=False, report=True, knowledge=True, codes=True, card=working.view(), **extra
        )
        review = await self.runner.run(CHECKER, turn, ctx)
        # Every question of the interpreter is asked, waived with a reason or asked as it was.
        questions, card.waived = settle_questions(working.questions, review)
        working.apply(review, self.keys)
        card.questions = merged([to_question(q) for q in questions], {})
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
            waived=[w.model_dump() for w in card.waived],
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
        typed: list[str] | None = None,
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
        replies = _replies(asked, values(job), messages, inputs, previous.revision, typed or [])
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
    typed: list[str],
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
    later = {m["id"] for m in messages if m["role"] == "user" and m["revision"] > revision}
    return replies + [m for m in inputs.messages if m.ref in later | set(typed)]


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
        if a.active
        and not a.draft
        and in_project(a, job)
        and (a.kind != "stl" or a.id == job.active_stl)
    ]


def with_notes(job: Job, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the user said about the part earlier in the chat, as the assistant retold it,
    comes first, as one more message of the user."""
    project = job.project
    if project is None or not project.notes:
        return messages
    note = {
        "id": f"notes:{project.number}",
        "role": "user",
        "kind": "chat",
        "revision": project.revision,
        "text": f"Из разговора в чате до начала проекта. {project.notes}",
        "created_at": project.started_at,
    }
    return [note, *messages]


def _card_files(card: TaskCard | None) -> set[str]:
    return {f.id for f in card.files} if card else set()
