"""Stage one: files and STL by code, interpretation by agents, readiness by deterministic gates.

The path the user waits on is kept short. The STL analysis, the quick triage and the deep
reading start together; the triage asks the main questions within seconds and the deep
reading never waits for the answers, which only the consolidation reads. Agents that read
the same data reuse their result.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ..domain.errors import AppError, OperationCancelled
from ..domain.fields import BY_KEY, FIELDS, triage_questions
from ..domain.hashing import digest
from ..domain.models import (
    Assumption,
    Attachment,
    Job,
    Question,
    SourceFile,
    Status,
    TaskCard,
    Verdict,
    identifier,
)
from ..domain.requirement_keys import RequirementKeys
from ..domain.rules import RULES_VERSION, assess, known
from ..domain.transitions import transition
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from .card import (
    apply_patch,
    card_questions,
    cited,
    discrepancy,
    first_questions,
    numbered,
    stable_references,
    summary,
    to_question,
    view,
)
from .concurrency import together
from .context import ContentBuilder, codes_block, collect
from .runner import AgentRunner, AgentSpec, RunContext, prompt
from .schemas import (
    Discrepancies,
    DomainReading,
    Draft,
    DraftQuestion,
    Gate,
    JudgeVerdict,
    Patch,
    Triage,
)
from .sources import ANALYZER_VERSION, Sources, StlFacts
from .store import RunStore
from .verification import SECOND_READER, Verifier

READING = ("view_page", "convert_units")
# Budgets sit near the 90th percentile of traced reasoning: they cut runaway tails only.
GATE = AgentSpec("gate", "Проверка темы", Gate, max_steps=1, thinking=False)
TRIAGE = AgentSpec("triage", "Главные вопросы", Triage, max_steps=1, thinking=False)
INTERPRETER = AgentSpec("interpreter", "Разбор ТЗ", Draft, READING, budget=9000)
ANALYSTS = (
    AgentSpec("analyst_loads", "Разбор нагрузок", DomainReading, READING, budget=8000),
    AgentSpec("analyst_environment", "Разбор среды", DomainReading, READING, budget=8000),
    AgentSpec("analyst_production", "Разбор производства", DomainReading, READING, budget=8000),
)
GEOMETRY = AgentSpec("analyst_geometry", "Разбор геометрии", DomainReading, READING, budget=8000)
CONSOLIDATOR = AgentSpec("consolidator", "Сводка", Patch, READING, budget=9000)
DISCREPANCIES = AgentSpec(
    "discrepancies", "Поиск несоответствий", Discrepancies, READING, max_steps=3, budget=4000
)
JUDGE = AgentSpec(
    "judge", "Итоговая оценка", JudgeVerdict, ("view_page",), max_steps=3, budget=6000
)
AGENTS = (
    GATE,
    TRIAGE,
    INTERPRETER,
    *ANALYSTS,
    GEOMETRY,
    CONSOLIDATOR,
    SECOND_READER,
    DISCREPANCIES,
    JUDGE,
)
UNITS_POLL_SECONDS = 2
# How often a running stage checks for a stop or a newer revision, even mid model call.
CHECK_SECONDS = 2
OFF_TOPIC = "Я помогаю подготовить задание на 3D печать. Приложите STL модель и ТЗ или опишите деталь"


@dataclass(frozen=True)
class Stage1Settings:
    model: str
    judge_threshold: float = 0.7
    timeout_seconds: float = 900
    job_images: int = 150


@dataclass
class Early:
    """What the user sees before the deep reading ends: the STL scale and the triage gaps."""

    card: TaskCard
    attachments: list[Attachment]
    asked: list[Question] = field(default_factory=list)
    title: str = ""

    def publish(self, job: Job) -> None:
        """Runs under the job lock, so the later of two publishers writes the fuller card."""
        card = self.card.model_copy(deep=True)
        card.questions = first_questions(card, self.asked, values(job))
        assess(card, failed(self.attachments))
        # Answers given from now on join this run instead of starting a new revision.
        job.card, job.phase = card, "deep"
        if job.title_source == "auto" and 2 < len(self.title) <= 60:
            job.title = self.title


class Stage1:
    def __init__(
        self,
        uow: UowFactory,
        files: Files,
        runner: AgentRunner,
        settings: Stage1Settings,
        codes: RequirementKeys,
    ):
        self.store, self.files, self.runner, self.settings = RunStore(uow), files, runner, settings
        self.sources, self.verifier = Sources(self.store, files), Verifier(runner, codes)
        self.codes = codes_block(codes)

    async def run(self, job_id: str, revision: int) -> None:
        ctx = RunContext(
            job_id=job_id,
            revision=revision,
            run_id=identifier(),
            check=partial(self.store.check, job_id, revision),
            event=partial(self.store.event, job_id, revision),
        )
        try:
            await asyncio.wait_for(self._guarded(ctx), self.settings.timeout_seconds)
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

    async def _guarded(self, ctx: RunContext) -> None:
        """A stop or a newer revision interrupts the run at once, even inside a model call."""
        work = asyncio.ensure_future(self._run(ctx))
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

    async def _run(self, ctx: RunContext) -> None:
        job = await self.store.update(ctx.job_id, ctx.revision, _started)
        attachments = _active(job, await self.store.attachments(job.id))
        messages = await self.store.messages(job.id)
        if await self._off_topic(job, attachments, messages, ctx):
            return
        await self.sources.prepare(attachments, ctx)
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
        early = Early(self._card(job, attachments, None), attachments)
        stl = asyncio.ensure_future(self._scale(job, attachments, early, ctx))
        try:
            asked, (draft, readings, facts) = await together(
                self._triage(job, content, early, ctx),
                self._read(job, attachments, stl, content, ctx),
            )
        finally:
            # Settled either way, so a failure of the analysis is never left unretrieved.
            stl.cancel()
            await asyncio.gather(stl, return_exceptions=True)
        card = self._card(job, attachments, facts)
        if facts is not None and facts.geometry.units == "unknown":
            # Only the geometry needs the scale; the rest is read and cached meanwhile.
            card.questions = first_questions(card, asked, values(await self.store.job(job.id)))
            await self.store.finish(
                ctx,
                assess(card, failed(attachments)),
                "Уточните единицы STL, чтобы сверить размеры",
            )
            return
        job = await self.store.update(ctx.job_id, ctx.revision, partial(_enter, "consolidate"))
        card = await self._interpret(job, draft, readings, asked, card, content, ctx)
        await self.store.finish(ctx, assess(card, failed(attachments)), summary(card))

    async def _off_topic(
        self, job: Job, attachments: list[Attachment], messages: list[dict], ctx: RunContext
    ) -> bool:
        """A message outside the print job gets a short reply and the card stays as it was.

        Only a revision started by that message alone is checked: new files always count.
        """
        chat = [m for m in messages if m["role"] == "user" and m.get("kind", "chat") == "chat"]
        files = {a.id for a in attachments}
        if not chat or chat[-1]["revision"] != ctx.revision or files != _card_files(job.card):
            return False
        gate = await self.runner.run(GATE, _gate_input(job, attachments, messages, chat), ctx)
        if gate.task:
            return False
        card = job.card.model_copy(update={"revision": ctx.revision}) if job.card else None
        reply = " ".join(gate.reply.split()) or OFF_TOPIC
        await self.store.finish(ctx, card, reply, offtopic=chat[-1]["id"])
        return True

    async def _scale(
        self, job: Job, attachments: list[Attachment], early: Early, ctx: RunContext
    ) -> StlFacts | None:
        async def ready(facts: StlFacts) -> None:
            # The scale question is shown as soon as the extents are known.
            early.card = self._card(job, attachments, facts)
            await self.store.update(ctx.job_id, ctx.revision, early.publish)

        return await self.sources.stl(job, attachments, ctx, ready)

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

    async def _triage(
        self, job: Job, content: ContentBuilder, early: Early, ctx: RunContext
    ) -> list[Question]:
        """Fields that no source covers become the first questions, shown within seconds.

        The triage only picks questions; its readings never reach the card. A field answered
        with "Не знаю" is asked again.
        """
        await ctx.event("triage.started", "Ищу главные вопросы")
        fields = [{"field": f.key, "что искать": f.hint} for f in FIELDS]
        result = await self.runner.run(
            TRIAGE, await content.build(answers=False, stl=False, fields=fields), ctx
        )
        answers = values(job)
        found = {f.field for f in result.fields if f.value.strip() and cited(f, ctx)}
        missing = [
            f.key for f in FIELDS if f.key not in found and not known(answers.get(f.question_id))
        ]
        proposals = {
            p.field: {"options": p.options, "suggested": p.suggested, "basis": p.basis}
            for p in result.questions
            if p.field in BY_KEY
        }
        early.asked = triage_questions(missing, proposals)
        early.title = " ".join(result.title.split())
        published = await self.store.update(ctx.job_id, ctx.revision, early.publish)
        assert published.card is not None
        open_questions = sum(not known(q.answer) for q in published.card.questions)
        await ctx.event(
            "triage.completed",
            f"Главных вопросов {open_questions}" if open_questions else "Главных вопросов нет",
            "completed",
        )
        return early.asked

    async def _read(
        self,
        job: Job,
        attachments: list[Attachment],
        stl: Awaitable[StlFacts | None],
        content: ContentBuilder,
        ctx: RunContext,
    ) -> tuple[Draft, dict[str, DomainReading], StlFacts | None]:
        """The interpreter and the domain analysts read the sources at once, independently.

        None of them sees the answers, so answering does not repeat this step. The geometry
        analyst alone depends on the STL scale and waits for it while the others work.
        """
        await ctx.event("interpretation.started", "Разбираю ТЗ и читаю источники по аспектам")
        base = await content.build(answers=False, stl=False, codes=True)
        production = await content.build(answers=False, stl=False, knowledge=True, codes=True)
        done = asyncio.Event()

        async def others() -> list:
            try:
                return await together(
                    self.runner.run(INTERPRETER, base, ctx),
                    self.runner.run(ANALYSTS[0], base, ctx),
                    self.runner.run(ANALYSTS[1], base, ctx),
                    self.runner.run(ANALYSTS[2], production, ctx),
                )
            finally:
                done.set()

        async def geometry() -> tuple[StlFacts | None, DomainReading | None]:
            facts = await stl
            while facts is not None and facts.geometry.units == "unknown":
                finished = done.is_set()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(done.wait(), UNITS_POLL_SECONDS)
                units = (await self.store.job(ctx.job_id)).units
                if units != "unknown":
                    scaled = job.model_copy(update={"units": units})
                    facts = await self.sources.stl(scaled, attachments, ctx)
                elif finished:
                    return facts, None
            if facts is None:
                return None, None
            ctx.stl_report = facts.report
            content.use_geometry(facts.geometry)
            reading = await self.runner.run(
                GEOMETRY, await content.build(answers=False, report=True, codes=True), ctx
            )
            return facts, reading

        (draft, loads, environment, production_reading), (facts, shape) = await together(
            others(), geometry()
        )
        readings = {
            "loads": loads,
            "environment": environment,
            "production": production_reading,
        }
        if shape is not None:
            readings["geometry"] = shape
        await ctx.event(
            "interpretation.completed",
            f"Найдено требований {len(draft.requirements)}",
            "completed",
        )
        return draft, readings, facts

    async def _consolidate(
        self,
        draft: Draft,
        readings: dict[str, DomainReading],
        asked: list[Question],
        content: ContentBuilder,
        ctx: RunContext,
        **extra: Any,
    ) -> Draft:
        patch = await self.runner.run(
            CONSOLIDATOR,
            await content.build(
                codes=True,
                draft=numbered(draft),
                readings={name: r.model_dump() for name, r in readings.items()},
                asked=[{"title": q.title, "answer": q.answer} for q in asked],
                **extra,
            ),
            ctx,
        )
        others = [q for reading in readings.values() for q in reading.questions]
        return apply_patch(draft, patch, draft.questions + others)

    async def _interpret(
        self,
        job: Job,
        draft: Draft,
        readings: dict[str, DomainReading],
        asked: list[Question],
        card: TaskCard,
        content: ContentBuilder,
        ctx: RunContext,
    ) -> TaskCard:
        answers = values(job)
        content.use_answers(job.answers)
        for question in asked:
            question.answer = answers.get(question.id)
        await ctx.event("consolidation.started", "Свожу прочтения в карточку")
        final = await self._consolidate(draft, readings, asked, content, ctx)
        requirements, questions = await self.verifier.check(final, answers, content, ctx)
        await ctx.event(
            "consolidation.completed", f"Требований в карточке {len(requirements)}", "completed"
        )
        await self.store.update(ctx.job_id, ctx.revision, partial(_enter, "verify"))
        await ctx.event("discrepancies.started", "Ищу несоответствия")
        await ctx.event("judge.started", "Проверяю итоговую интерпретацию")
        current = view(final, requirements, questions)
        found, verdict = await together(
            self.runner.run(
                DISCREPANCIES, await content.build(card=current, report=True, knowledge=True), ctx
            ),
            self.runner.run(JUDGE, await content.build(card=current), ctx),
        )
        discrepancies = [discrepancy(item) for item in found.discrepancies]
        asked = _still_asked(asked, final.questions)
        await ctx.event(
            "discrepancies.completed",
            f"Несоответствий {len(discrepancies)}",
            "warning" if discrepancies else "completed",
        )
        reworked = verdict.score < self.settings.judge_threshold
        if reworked:
            final = await self._consolidate(
                final, readings, asked, content, ctx, remarks=verdict.remarks
            )
            requirements, questions = await self.verifier.check(final, answers, content, ctx)
            current = view(final, requirements, questions + discrepancies)
            verdict = await self.runner.run(JUDGE, await content.build(card=current), ctx)
        passed = verdict.score >= self.settings.judge_threshold
        await ctx.event(
            "judge.completed",
            "Интерпретация проверена" if passed else "Интерпретация не прошла проверку",
            "completed" if passed else "warning",
        )
        purpose = answers.get("purpose", "")
        card.purpose = purpose if known(purpose) else final.purpose
        card.requirements = requirements
        card.preferences = final.preferences
        card.production_constraints = final.production_constraints
        card.assumptions = [Assumption(**a.model_dump()) for a in final.assumptions]
        card.unknowns = final.unknowns
        card.verdict = Verdict(
            score=verdict.score,
            passed=passed,
            reworked=reworked,
            remarks=[r.model_dump() for r in verdict.remarks],
        )
        card.questions = card_questions(
            card, final.questions, asked + questions + discrepancies, answers
        )
        card.versions.update(
            {f"prompt.{a.name}": digest(prompt(a.name)) for a in AGENTS},
            model=self.settings.model,
        )
        stable_references(card, ctx)
        return card

def values(job: Job) -> dict[str, str]:
    return {key: answer.value for key, answer in job.answers.items()}


def failed(attachments: list[Attachment]) -> list[str]:
    return [a.filename for a in attachments if a.status == "failed"]


def _started(job: Job) -> None:
    job.status = transition(job.status, Status.RUNNING)
    job.phase = "triage"


def _enter(phase: str, job: Job) -> None:
    """From here answers given later need a new revision; earlier ones are read now."""
    job.phase = phase  # type: ignore[assignment]


def _active(job: Job, attachments: list[Attachment]) -> list[Attachment]:
    return [
        a
        for a in attachments
        if a.active and not a.draft and (a.kind != "stl" or a.id == job.active_stl)
    ]


def _card_files(card: TaskCard | None) -> set[str]:
    return {f.id for f in card.files} if card else set()


def _still_asked(asked: list[Question], drafted: list[DraftQuestion]) -> list[Question]:
    """An answered triage question stays and is not asked again. An open one gives way to
    the consolidation's sharper question about the same field; a blocking one stays."""
    reasked = {to_question(q).id for q in drafted}
    return [
        q
        for q in asked
        if q.answer is not None or (q.blocking and q.id != "purpose" and q.id not in reasked)
    ]


def _gate_input(
    job: Job, attachments: list[Attachment], messages: list[dict], chat: list[dict]
) -> list[dict[str, Any]]:
    """Only the chat around the latest message: the gate must answer in a second or two."""
    assistant = next((m["text"] for m in reversed(messages) if m["role"] == "assistant"), "")
    blocks = {
        "messages": [m["text"] for m in chat[-6:-1]],
        "assistant": assistant,
        "files": [a.filename for a in attachments],
        "purpose": job.card.purpose if job.card else "",
        "latest": chat[-1]["text"],
    }
    text = "\n\n".join(
        f"<{name}>\n{json.dumps(value, ensure_ascii=False)}\n</{name}>"
        for name, value in blocks.items()
    )
    return [{"type": "text", "text": text}]
