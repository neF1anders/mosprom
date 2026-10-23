"""Stage one: files and STL by code, interpretation by agents, readiness by deterministic gates.

The path the user waits on is kept short. A quick triage without reasoning asks the main
questions within seconds; the deep reading runs meanwhile and does not wait for the answers,
which only the consolidation reads. Agents that read the same data reuse their result.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from functools import partial
from typing import Any

from ..domain.errors import AppError, OperationCancelled
from ..domain.evidence import (
    apply_decision,
    check_citations,
    digest,
    display,
    normalize_text,
    reconcile,
    reference,
    same_quantity,
    verify_question,
)
from ..domain.fields import BY_KEY, FIELDS, triage_questions
from ..domain.geometry import bind_analysis, summarize
from ..domain.models import (
    DOCUMENT_VERSION,
    Assumption,
    Attachment,
    Event,
    Evidence,
    Geometry,
    Job,
    Knowledge,
    Message,
    Question,
    Requirement,
    SourceFile,
    Status,
    StlAnalysis,
    TaskCard,
    Verdict,
    identifier,
)
from ..domain.rules import RULES_VERSION, assess, known, purpose_question, units_question
from ..domain.transitions import transition
from ..ports.operations import Files
from ..ports.persistence import UowFactory
from ..services.commands import fingerprint
from .context import ContentBuilder, Inputs, collect
from .runner import AgentRunner, AgentSpec, RunContext, prompt
from .schemas import (
    Discrepancies,
    DomainReading,
    Draft,
    DraftQuestion,
    DraftRequirement,
    JudgeVerdict,
    Patch,
    SecondReading,
    Triage,
    TriageField,
)

ANALYZER_VERSION = "1.2-partial"
ALL_TOOLS = ("search_knowledge", "read_stl_report", "view_page", "convert_units")
READING = ("view_page", "convert_units")
# Budgets sit near the 90th percentile of traced reasoning: they cut runaway tails only.
TRIAGE = AgentSpec("triage", "Главные вопросы", Triage, max_steps=1, thinking=False)
INTERPRETER = AgentSpec("interpreter", "Разбор ТЗ", Draft, READING, budget=9000)
ANALYSTS = (
    AgentSpec("analyst_loads", "Разбор нагрузок", DomainReading, READING, budget=8000),
    AgentSpec("analyst_environment", "Разбор среды", DomainReading, READING, budget=8000),
    AgentSpec(
        "analyst_production",
        "Разбор производства",
        DomainReading,
        ("view_page", "search_knowledge", "convert_units"),
        budget=8000,
    ),
)
GEOMETRY = AgentSpec(
    "analyst_geometry",
    "Разбор геометрии",
    DomainReading,
    ("view_page", "read_stl_report", "convert_units"),
    budget=8000,
)
CONSOLIDATOR = AgentSpec("consolidator", "Сводка", Patch, READING, budget=9000)
SECOND_READER = AgentSpec("second_reading", "Второе чтение", SecondReading, max_steps=1)
DISCREPANCIES = AgentSpec(
    "discrepancies", "Поиск несоответствий", Discrepancies, ALL_TOOLS, max_steps=3, budget=4000
)
JUDGE = AgentSpec(
    "judge", "Итоговая оценка", JudgeVerdict, ("view_page",), max_steps=3, budget=6000
)
AGENTS = (
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
QUOTE_PARTS = re.compile(r"\.{3}|…|(?<=[.!?;])\s+|\n")


@dataclass(frozen=True)
class Stage1Settings:
    model: str
    judge_threshold: float = 0.7
    timeout_seconds: float = 3600
    job_images: int = 150


@dataclass(frozen=True)
class StlFacts:
    attachment: Attachment
    report: dict[str, Any]
    analysis: StlAnalysis
    geometry: Geometry


class Stage1:
    def __init__(
        self, uow: UowFactory, files: Files, runner: AgentRunner, settings: Stage1Settings
    ):
        self.uow, self.files, self.runner, self.settings = uow, files, runner, settings

    async def run(self, job_id: str, revision: int) -> None:
        ctx = RunContext(
            job_id=job_id,
            revision=revision,
            run_id=identifier(),
            check=partial(self._check, job_id, revision),
            event=partial(self._event, job_id, revision),
        )
        try:
            await asyncio.wait_for(self._run(ctx), self.settings.timeout_seconds)
        except OperationCancelled:
            await self._cancel(job_id)
        except TimeoutError:
            await self._fail(ctx, "Обработка заняла слишком много времени", "stage1_timeout")
        except AppError as exc:
            await self._fail(ctx, exc.message, exc.code)
        except Exception:
            # A bug must not leave the job running forever; the queue still records the failure.
            await self._fail(ctx, "Внутренняя ошибка обработки, попробуйте ещё раз", "internal")
            raise

    async def _run(self, ctx: RunContext) -> None:
        job = await self._start(ctx)
        attachments = await self._prepare(job, ctx)
        stl = await self._stl(job, attachments, ctx)
        failed = [a.filename for a in attachments if a.status == "failed"]
        card = TaskCard(
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
        inputs = await self._inputs(job, attachments, stl, ctx)
        content = ContentBuilder(self.files, inputs, ctx, await self._knowledge())
        asked = await self._triage(job, card, failed, content, ctx)
        draft, readings, stl = await self._read(job, attachments, stl, content, ctx)
        if stl is not None:
            card.geometry, card.stl_analysis = stl.geometry, stl.analysis
        if stl is not None and stl.geometry.units == "unknown":
            # Only the geometry needs the scale; the rest is read and cached meanwhile.
            async with self.uow() as uow:
                answers = (await uow.jobs.get(ctx.job_id)).answers
            card.questions = _first_questions(card, asked, answers)
            await self._finish(
                ctx, assess(card, failed), "Уточните единицы STL, чтобы сверить размеры"
            )
            return
        job = await self._enter(ctx, "consolidate")
        card = await self._interpret(job, draft, readings, asked, card, content, ctx)
        await self._finish(ctx, assess(card, failed), _summary(card))

    async def _start(self, ctx: RunContext) -> Job:
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            if job.revision != ctx.revision or job.status in {Status.STOPPING, Status.STOPPED}:
                raise OperationCancelled()
            job.status = transition(job.status, Status.RUNNING)
            job.phase = "triage"
            await uow.jobs.save(job)
            await uow.commit()
        return job

    async def _prepare(self, job: Job, ctx: RunContext) -> list[Attachment]:
        async with self.uow() as uow:
            attachments = await uow.jobs.attachments(job.id)
        active = [
            a
            for a in attachments
            if a.active and not a.draft and (a.kind != "stl" or a.id == job.active_stl)
        ]
        await ctx.event("files.started", "Читаю файлы")
        for attachment in active:
            if attachment.kind == "stl" or not _outdated(attachment):
                continue
            await ctx.check()
            try:
                result = await self.files.inspect(attachment.id, attachment.kind)
                attachment.fragments, attachment.artifacts = (
                    result["fragments"],
                    result["artifacts"],
                )
                attachment.status, attachment.error = "completed", None
                attachment.parser_version = DOCUMENT_VERSION
            except AppError as exc:
                attachment.status, attachment.error = "failed", exc.message
            await self._save(attachment)
        failed = [a.filename for a in active if a.status == "failed" and a.kind != "stl"]
        await ctx.event(
            "files.failed" if failed else "files.completed",
            "Не все файлы прочитаны" if failed else "Файлы прочитаны",
            "failed" if failed else "completed",
            failed=failed,
        )
        return active

    async def _stl(self, job: Job, active: list[Attachment], ctx: RunContext) -> StlFacts | None:
        attachment = next((a for a in active if a.id == job.active_stl), None)
        if attachment is None:
            return None
        await ctx.check()
        await ctx.event("stl.started", "Анализирую STL")
        key = fingerprint([attachment.sha256, job.units, ANALYZER_VERSION, 128])
        try:
            async with self.uow() as uow:
                report = await uow.jobs.cache(key)
            if report is None:
                report = await self.files.analyze(attachment.id, job.units, key)
                async with self.uow() as uow:
                    await uow.jobs.cache_put(key, report)
                    await uow.commit()
            analysis = bind_analysis(attachment, job.units, report)
        except AppError as exc:
            attachment.status, attachment.error = "failed", exc.message
            await self._save(attachment)
            await ctx.event("stl.failed", exc.message, "failed")
            return None
        geometry = summarize(report, job.units, key)
        attachment.status, attachment.error = "completed", None
        attachment.artifacts = list(
            dict.fromkeys(
                [*attachment.artifacts, key + ".json", *filter(None, [geometry.preview_id])]
            )
        )
        await self._save(attachment)
        status = "warning" if geometry.defects else "completed"
        await ctx.event(
            "stl.completed", "STL проанализирован", status, geometry=geometry.model_dump()
        )
        return StlFacts(attachment, report, analysis, geometry)

    async def _inputs(
        self, job: Job, attachments: list[Attachment], stl: StlFacts | None, ctx: RunContext
    ) -> Inputs:
        messages: list[dict[str, Any]] = []
        before = None
        while True:
            async with self.uow() as uow:
                page = await uow.jobs.messages(job.id, before, 100)
            messages = page + messages
            if len(page) < 100:
                break
            before = page[0]["seq"]
        inputs = collect(messages, attachments, job.answers, stl.geometry if stl else None)
        if inputs.images() > self.settings.job_images:
            raise AppError(
                f"В задании больше {self.settings.job_images} страниц и изображений, "
                "уберите лишние файлы",
                "too_many_pages",
                413,
            )
        ctx.sources.update(inputs.sources())
        ctx.stl_report = stl.report if stl else None
        return inputs

    async def _knowledge(self) -> list[Knowledge]:
        async with self.uow() as uow:
            return await uow.knowledge.all()

    async def _triage(
        self, job: Job, card: TaskCard, failed: list[str], content: ContentBuilder, ctx: RunContext
    ) -> list[Question]:
        """Fields that no source covers become the first questions, shown within seconds.

        The triage only picks questions; its readings never reach the card.
        """
        await ctx.event("triage.started", "Ищу главные вопросы")
        fields = [{"field": f.key, "что искать": f.hint} for f in FIELDS]
        result = await self.runner.run(
            TRIAGE, await content.build(answers=False, stl=False, fields=fields), ctx
        )
        found = {f.field for f in result.fields if f.value.strip() and _cited(f, ctx)}
        missing = [f.key for f in FIELDS if f.key not in found and f.question_id not in job.answers]
        proposals = {
            p.field: {"options": p.options, "suggested": p.suggested, "basis": p.basis}
            for p in result.questions
            if p.field in BY_KEY
        }
        asked = triage_questions(missing, proposals)
        provisional = card.model_copy(deep=True)
        provisional.questions = _first_questions(provisional, asked, job.answers)
        assess(provisional, failed)
        async with self.uow() as uow:
            current = await uow.jobs.get(ctx.job_id, lock=True)
            if current.revision != ctx.revision or current.status in {
                Status.STOPPING,
                Status.STOPPED,
            }:
                raise OperationCancelled()
            current.card, current.phase = provisional, "deep"
            title = " ".join(result.title.split())
            if current.title_source == "auto" and 2 < len(title) <= 60:
                current.title = title
            await uow.jobs.save(current)
            await uow.commit()
        open_questions = [q for q in provisional.questions if not known(q.answer)]
        await ctx.event(
            "triage.completed",
            f"Главных вопросов {len(open_questions)}" if open_questions else "Главных вопросов нет",
            "completed",
        )
        return asked

    async def _read(
        self,
        job: Job,
        attachments: list[Attachment],
        stl: StlFacts | None,
        content: ContentBuilder,
        ctx: RunContext,
    ) -> tuple[Draft, dict[str, DomainReading], StlFacts | None]:
        """The interpreter and the domain analysts read the sources at once, independently.

        None of them sees the answers, so answering does not repeat this step. The geometry
        analyst alone depends on the STL scale and waits for it while the others work.
        """
        await ctx.event("interpretation.started", "Разбираю ТЗ и читаю источники по аспектам")
        base = await content.build(answers=False, stl=False)
        production = await content.build(answers=False, stl=False, knowledge=True)
        done = asyncio.Event()

        async def others() -> list:
            try:
                return await _together(
                    self.runner.run(INTERPRETER, base, ctx),
                    self.runner.run(ANALYSTS[0], base, ctx),
                    self.runner.run(ANALYSTS[1], base, ctx),
                    self.runner.run(ANALYSTS[2], production, ctx),
                )
            finally:
                done.set()

        async def geometry() -> tuple[StlFacts | None, DomainReading | None]:
            facts = stl
            while facts is not None and facts.geometry.units == "unknown":
                finished = done.is_set()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(done.wait(), UNITS_POLL_SECONDS)
                units = await self._units(ctx.job_id)
                if units != "unknown":
                    facts = await self._stl(
                        job.model_copy(update={"units": units}), attachments, ctx
                    )
                elif finished:
                    return facts, None
            if facts is None:
                return None, None
            ctx.stl_report = facts.report
            content.use_geometry(facts.geometry)
            reading = await self.runner.run(
                GEOMETRY, await content.build(answers=False, report=True), ctx
            )
            return facts, reading

        (draft, loads, environment, production_reading), (facts, shape) = await _together(
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

    async def _units(self, job_id: str) -> str:
        async with self.uow() as uow:
            return (await uow.jobs.get(job_id)).units

    async def _enter(self, ctx: RunContext, phase: str) -> Job:
        """From here answers given later need a new revision; earlier ones are read now."""
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            if job.revision != ctx.revision or job.status in {Status.STOPPING, Status.STOPPED}:
                raise OperationCancelled()
            job.phase = phase  # type: ignore[assignment]
            await uow.jobs.save(job)
            await uow.commit()
        return job

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
                draft=_numbered(draft),
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
        answers = {key: answer.value for key, answer in job.answers.items()}
        content.use_answers(job.answers)
        for question in asked:
            question.answer = answers.get(question.id)
        await ctx.event("consolidation.started", "Свожу прочтения в карточку")
        final = await self._consolidate(draft, readings, asked, content, ctx)
        requirements, questions = await self._check_requirements(final, answers, content, ctx)
        await ctx.event(
            "consolidation.completed", f"Требований в карточке {len(requirements)}", "completed"
        )
        await self._enter(ctx, "verify")
        await ctx.event("discrepancies.started", "Ищу несоответствия")
        await ctx.event("judge.started", "Проверяю итоговую интерпретацию")
        view = _view(final, requirements, questions)
        found, verdict = await _together(
            self.runner.run(
                DISCREPANCIES, await content.build(card=view, report=True, knowledge=True), ctx
            ),
            self.runner.run(JUDGE, await content.build(card=view), ctx),
        )
        discrepancies = [_discrepancy(item) for item in found.discrepancies]
        # An answered triage question stays and is not asked again. An open one gives way to
        # the consolidation's sharper question about the same field; a blocking one stays.
        reasked = {_drafted(q).id for q in final.questions}
        asked = [
            q
            for q in asked
            if q.answer is not None or (q.blocking and q.id != "purpose" and q.id not in reasked)
        ]
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
            requirements, questions = await self._check_requirements(final, answers, content, ctx)
            view = _view(final, requirements, questions + discrepancies)
            verdict = await self.runner.run(JUDGE, await content.build(card=view), ctx)
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
        card.questions = self._questions(
            card, final.questions, asked + questions + discrepancies, answers
        )
        card.versions.update(
            {f"prompt.{a.name}": digest(prompt(a.name)) for a in AGENTS},
            model=self.settings.model,
        )
        _stable_references(card, ctx)
        return card

    async def _check_requirements(
        self, draft: Draft, answers: dict[str, str], content: ContentBuilder, ctx: RunContext
    ) -> tuple[list[Requirement], list[Question]]:
        checked, questions, pending = [], [], []
        for requirement in map(_requirement, draft.requirements):
            question_id = "verify." + reference(requirement)
            if known(answers.get(question_id)):
                questions.append(verify_question(requirement, "Значение подтверждено вами", []))
                checked.append(
                    apply_decision(requirement, question_id, answers[question_id], [requirement])
                )
                continue
            status = check_citations(requirement, ctx.sources)
            requirement.verified = status == "verified"
            if status == "vision":
                pending.append(requirement)
            elif status == "rejected" and requirement.mandatory:
                impact = "Значение не найдено в источнике дословно"
                questions.append(verify_question(requirement, impact, [display(requirement)]))
            checked.append(requirement)
        for requirement, reading in await self._second_reading(pending, content, ctx):
            if requirement.mandatory:
                impact = "Значение прочитано с изображения по-разному"
                questions.append(
                    verify_question(requirement, impact, [display(requirement), reading])
                )
        merged, conflicts = reconcile(checked, ctx.sources, answers)
        return merged, questions + conflicts

    async def _second_reading(
        self, pending: list[Requirement], content: ContentBuilder, ctx: RunContext
    ) -> list[tuple[Requirement, str]]:
        """Image readings count only when an independent reading of the page agrees."""
        by_source: dict[str, list[Requirement]] = {}
        for requirement in pending:
            for evidence in requirement.sources:
                if evidence.method == "vision":
                    by_source.setdefault(evidence.source_id, []).append(requirement)
        mismatches: dict[int, tuple[Requirement, str]] = {}
        for source_id, requirements in by_source.items():
            readings = await self._read_page(source_id, requirements, content, ctx)
            for requirement in requirements:
                reading = readings.get(requirement.key)
                agrees = (
                    reading is not None
                    and reading.legible
                    and same_quantity(requirement, reading.value, reading.unit or requirement.unit)
                )
                if not agrees:
                    mismatches[id(requirement)] = (requirement, _reading(reading))
        for requirement in pending:
            requirement.verified = id(requirement) not in mismatches
        return list(mismatches.values())

    async def _read_page(self, source_id, requirements, content, ctx) -> dict[str, Any]:
        source = ctx.sources[source_id]
        items = [
            {"key": r.key, "label": r.label, "conditions": r.conditions, "unit": r.unit}
            for r in requirements
        ]
        key = fingerprint(["second-reading", digest(prompt("second_reading")), source.image, items])
        async with self.uow() as uow:
            cached = await uow.jobs.cache(key)
        if cached is None:
            text = "<items>\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n</items>"
            parts = [{"type": "text", "text": text}]
            parts.extend(await content.image(source.image or "", f"Страница {source.id}"))
            reading = await self.runner.run(SECOND_READER, parts, ctx)
            cached = reading.model_dump()
            async with self.uow() as uow:
                await uow.jobs.cache_put(key, cached)
                await uow.commit()
        return {r.key: r for r in SecondReading.model_validate(cached).readings}

    def _questions(
        self,
        card: TaskCard,
        drafted: list[DraftQuestion],
        derived: list[Question],
        answers: dict[str, str],
    ) -> list[Question]:
        questions: list[Question] = []
        if card.geometry is not None:
            questions.append(units_question(card.geometry))
        if not card.purpose.strip() or "purpose" in answers:
            questions.append(purpose_question())
        questions.extend(derived)
        questions.extend(_drafted(q) for q in drafted)
        unique: dict[str, Question] = {}
        for question in questions:
            unique.setdefault(question.id, question)
        for question in unique.values():
            question.answer = answers.get(question.id)
        return list(unique.values())

    async def _finish(self, ctx: RunContext, card: TaskCard, text: str) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            if job.revision != ctx.revision or job.status in {Status.STOPPING, Status.STOPPED}:
                raise OperationCancelled()
            # Files attached during the run are not in this card, so it is not handed over.
            if job.files_changed:
                text = "Файлы изменились, отправьте задание, чтобы я их учёл"
            blocked = card.readiness == "blocked" or job.files_changed
            job.card, job.error, job.phase = card, None, None
            job.status = transition(job.status, Status.WAITING if blocked else Status.COMPLETED)
            if not blocked:
                await uow.queue.stage2(job.id, job.revision)
                job.next_stage = "queued"
            await uow.jobs.save(job)
            await uow.jobs.message(
                Message(job_id=job.id, revision=job.revision, role="assistant", text=text)
            )
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="stage1.completed",
                    status=job.status,
                    message=text,
                    data={"readiness": card.readiness},
                )
            )
            await uow.commit()

    async def _check(self, job_id: str, revision: int) -> None:
        async with self.uow() as uow:
            head = await uow.jobs.head(job_id)
        if head.revision != revision or head.status in {Status.STOPPING, Status.STOPPED}:
            raise OperationCancelled()

    async def _event(
        self, job_id: str, revision: int, type: str, message: str, status: str = "running", **data
    ) -> None:
        async with self.uow() as uow:
            await uow.events.append(
                Event(
                    job_id=job_id,
                    revision=revision,
                    type=type,
                    status=status,
                    message=message,
                    data=data,
                )
            )
            await uow.commit()

    async def _save(self, attachment: Attachment) -> None:
        async with self.uow() as uow:
            await uow.jobs.attachment(attachment)
            await uow.commit()

    async def _cancel(self, job_id: str) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            if job.status == Status.STOPPING:
                job.status = transition(job.status, Status.STOPPED)
                job.phase = None
                await uow.jobs.save(job)
                await uow.commit()

    async def _fail(self, ctx: RunContext, message: str, code: str) -> None:
        async with self.uow() as uow:
            job = await uow.jobs.get(ctx.job_id, lock=True)
            if job.revision != ctx.revision:
                return
            if job.status in {Status.STOPPING, Status.STOPPED}:
                job.status = Status.STOPPED
            else:
                job.status, job.error = transition(job.status, Status.FAILED), message
            job.phase = None
            await uow.jobs.save(job)
            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="operation.failed",
                    status=job.status,
                    message=message,
                    data={"code": code},
                )
            )
            await uow.commit()


async def _together(*steps: Awaitable[Any]) -> list[Any]:
    """Runs steps at once; the first failure cancels the rest and is raised as it is."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks: list[asyncio.Task[Any]] = [
                group.create_task(step)  # type: ignore[arg-type]
                for step in steps
            ]
    except BaseExceptionGroup as group_error:
        raise group_error.exceptions[0] from None
    return [task.result() for task in tasks]


def _first_questions(card: TaskCard, asked: list[Question], answers: dict) -> list[Question]:
    """Questions shown before the deep reading: the STL scale and the triage gaps."""
    questions = [units_question(card.geometry)] if card.geometry is not None else []
    unique: dict[str, Question] = {}
    for question in questions + [q.model_copy() for q in asked]:
        unique.setdefault(question.id, question)
    for question in unique.values():
        answer = answers.get(question.id)
        question.answer = answer.value if answer is not None else None
    return list(unique.values())


def _cited(field: TriageField, ctx: RunContext) -> bool:
    """A triage reading counts only with a quote the source really contains."""
    source = ctx.sources.get(field.source_id or "")
    if source is None or field.field not in BY_KEY:
        return False
    if source.image is not None:
        return True
    # A quick reading joins sentences from several places; each one must be verbatim.
    text = normalize_text(source.text)
    parts = [normalize_text(p).rstrip(".") for p in re.split(QUOTE_PARTS, field.quote)]
    parts = [p for p in parts if len(p) >= 3]
    return bool(parts) and all(p in text for p in parts)


def _numbered(draft: Draft) -> dict[str, Any]:
    """The consolidator edits requirements by these ids, so its answer stays short."""
    view = draft.model_dump()
    view["requirements"] = [
        {"id": f"r{index}", **requirement}
        for index, requirement in enumerate(view["requirements"], 1)
    ]
    return view


def apply_patch(draft: Draft, patch: Patch, questions: list[DraftQuestion]) -> Draft:
    """Applies the consolidator's edit; ids it does not know are ignored."""
    ids = {f"r{index}": r for index, r in enumerate(draft.requirements, 1)}
    removed = {item.id for item in patch.remove}
    changed = {
        item.id: DraftRequirement(**item.model_dump(exclude={"id"}))
        for item in patch.change
        if item.id in ids
    }
    kept = [changed.get(key, r) for key, r in ids.items() if key not in removed]
    return Draft(
        purpose=draft.purpose if patch.purpose is None else patch.purpose,
        requirements=kept + patch.add,
        preferences=draft.preferences if patch.preferences is None else patch.preferences,
        production_constraints=draft.production_constraints
        if patch.production_constraints is None
        else patch.production_constraints,
        assumptions=draft.assumptions if patch.assumptions is None else patch.assumptions,
        unknowns=draft.unknowns if patch.unknowns is None else patch.unknowns,
        questions=_unique_questions(questions) if patch.questions is None else patch.questions,
    )


def _unique_questions(questions: list[DraftQuestion]) -> list[DraftQuestion]:
    unique: dict[str, DraftQuestion] = {}
    for question in questions:
        unique.setdefault(question.field or normalize_text(question.title), question)
    return list(unique.values())


def _drafted(question: DraftQuestion) -> Question:
    """A question about a triage field keeps the field's id, so its answer is never lost."""
    field = BY_KEY.get(question.field or "")
    return Question(
        id=field.question_id if field else "clarify." + digest(normalize_text(question.title)),
        kind="clarify",
        title=question.title,
        impact=question.impact,
        options=question.options,
        suggested=question.suggested if question.basis else None,
        basis=question.basis,
        blocking=question.blocking,
    )


def _outdated(attachment: Attachment) -> bool:
    return attachment.status == "pending" or (
        attachment.status == "completed" and attachment.parser_version != DOCUMENT_VERSION
    )


def _requirement(draft: DraftRequirement) -> Requirement:
    return Requirement(
        **draft.model_dump(exclude={"sources"}),
        sources=[Evidence(**c.model_dump()) for c in draft.sources],
    )


def _discrepancy(item) -> Question:
    anchor = item.requirement_key or normalize_text(item.title)
    return Question(
        id=f"{item.kind}." + digest(anchor),
        kind="discrepancy",
        title=item.title,
        impact=item.impact,
        options=item.options,
        suggested=item.suggested if item.basis else None,
        basis=item.basis,
        sources=[Evidence(**c.model_dump()) for c in item.sources],
        requirement_key=item.requirement_key,
    )


def _view(draft: Draft, requirements: list[Requirement], questions: list[Question]) -> dict:
    return {
        "purpose": draft.purpose,
        "requirements": [r.model_dump(exclude={"superseded"}) for r in requirements],
        "preferences": draft.preferences,
        "production_constraints": draft.production_constraints,
        "assumptions": [a.model_dump() for a in draft.assumptions],
        "unknowns": draft.unknowns,
        "questions": [q.model_dump() for q in questions]
        + [q.model_dump() for q in draft.questions],
    }


def _stable_references(card: TaskCard, ctx: RunContext) -> None:
    """Agents cite short run-local ids; the card keeps references that outlive the run."""
    evidences = [e for r in card.requirements for e in r.sources]
    evidences += [e for r in card.requirements for s in r.superseded for e in s.sources]
    evidences += [e for q in card.questions for e in q.sources]
    for evidence in evidences:
        source = ctx.sources.get(evidence.source_id)
        if source is not None:
            evidence.source_id = source.ref


def _summary(card: TaskCard) -> str:
    open_questions = [q for q in card.questions if not known(q.answer)]
    text = (
        "Задание разобрано, передаю на подбор параметров"
        if card.readiness != "blocked"
        else f"Задание разобрано, нужны ответы на вопросы, всего {len(open_questions)}"
        if open_questions
        else "Задание разобрано, но подбор параметров пока заблокирован"
    )
    remarks = (
        [r.text for r in card.verdict.remarks if r.severity != "minor"] if card.verdict else []
    )
    if remarks:
        text += ". Проверка отметила " + ". ".join(remarks)
    return text


def _reading(reading: Any) -> str:
    if reading is None or not reading.value:
        return ""
    return f"{reading.value} {reading.unit or ''}".strip()
