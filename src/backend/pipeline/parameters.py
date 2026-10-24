"""Parameter selection, its check, slicing and the check of the G-code for a ready card.

Selection and both checks are deterministic and quick, so the steps run back to back in one
task instead of handing over through the queue. Slicing takes minutes in STE Slicer and is
watched meanwhile, so a stop or an edit ends it at once. Each step commits its result, event
and summary under the revision guard, so the chat follows step by step.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from ..domain.catalog import MODE_NAMES, Catalog
from ..domain.errors import AppError, OperationCancelled
from ..domain.models import (
    Event,
    Job,
    Message,
    Outcome,
    ParametersSummary,
    ResultSummary,
    Status,
    TaskCard,
)
from ..domain.parameters import CheckResult, Feedback, ParameterSet
from ..domain.pipeline import FIRST_STEP, Step, Verdict, next_step
from ..domain.slicing import GcodeCheck, SliceReport
from ..domain.transitions import transition
from ..ports.operations import Slicer
from ..ports.persistence import UnitOfWork, UowFactory
from .store import JobStore, SafePoint, ensure_current, no_safe_point

# The summary of a finished project, written after the pipeline's last transaction.
Report = Callable[[str], Awaitable[None]]

Select = Callable[[TaskCard, Feedback | None], ParameterSet]
Check = Callable[[ParameterSet], CheckResult]
# The stored G-code by its key, the set it was sliced from and the pass.
CheckGcode = Callable[[str, ParameterSet, int], GcodeCheck]
# How often a running slicing looks whether the job was stopped or edited.
WATCH_SECONDS = 1.0
T = TypeVar("T")


@dataclass(frozen=True)
class PipelineSettings:
    # Selection and the checks take well under a second. Slicing is bounded by the slicer
    # itself, which knows how long a run waits for another job's.
    timeout_seconds: float


@dataclass
class Run:
    """What the passes found so far; a new selection starts its pass afresh."""

    parameter_set: ParameterSet
    check: CheckResult | None = None
    report: SliceReport | None = None
    feedback: Feedback | None = None


class ParameterPipeline:
    def __init__(
        self,
        uow: UowFactory,
        catalog: Catalog,
        select: Select,
        check: Check,
        slicer: Slicer,
        check_gcode: CheckGcode,
        settings: PipelineSettings,
        *,
        safe_point: SafePoint = no_safe_point,
        report: Report | None = None,
    ):
        # Without a report of its own the finished pipeline says its outcome in one line.
        self.store = ParameterStore(uow, say=report is None)
        self.catalog, self.select, self.check = catalog, select, check
        self.slicer, self.check_gcode = slicer, check_gcode
        self.settings, self.safe_point, self.report = settings, safe_point, report

    async def run(self, job_id: str, revision: int) -> None:
        try:
            await self._run(job_id, revision)
        except OperationCancelled:
            await self.store.cancel(job_id)
        except TimeoutError:
            message = "Подбор параметров занял слишком много времени"
            await self.store.fail(job_id, revision, message, "parameters_timeout")
        except AppError as exc:
            await self.store.fail(job_id, revision, exc.message, exc.code)
        except Exception:
            message = "Внутренняя ошибка подбора параметров, попробуйте ещё раз"
            await self.store.fail(job_id, revision, message, "internal")
            raise

    async def _run(self, job_id: str, revision: int) -> None:
        job = await self.store.update(job_id, revision, _started)
        card = _card(job)
        step: Step | None = FIRST_STEP
        run: Run | None = None
        while step is not None:
            await self.store.check(job_id, revision)
            if step.stage == "parameters":
                feedback = run.feedback if run else None
                run = Run(await self._select(job, step, card, feedback))
                step = await self._selected(job, step, run)
            else:
                assert run is not None, "every pass starts with a selection"
                step = await self._steps[step.stage](job, step, run)
            if step is None and self.report is not None:
                await self.report(job_id)
            # Messages queued meanwhile are read before the next step spends its time, and
            # after the last one, when the job is done.
            if await self.safe_point(job_id, revision):
                return

    @property
    def _steps(self) -> dict[str, Callable[[Job, Step, Run], Awaitable[Step | None]]]:
        return {"validation": self._validated, "slicing": self._sliced, "gcode": self._gcode}

    async def _selected(self, job: Job, step: Step, run: Run) -> Step | None:
        following = next_step(step, _verdict(run.parameter_set))
        summary = summarize(run.parameter_set, self.catalog)
        await self.store.selected(job, step, run, summary, following)
        return following

    async def _validated(self, job: Job, step: Step, run: Run) -> Step | None:
        run.check = await self._check(job, step, run.parameter_set)
        run.feedback = run.check.feedback
        following = next_step(step, run.feedback.result)
        await self.store.checked(job, step, run, following)
        return following

    async def _sliced(self, job: Job, step: Step, run: Run) -> Step | None:
        run.report = await self._slice(job, step, run.parameter_set)
        following = next_step(step, "ok" if run.report.status == "sliced" else "failed")
        await self.store.sliced(job, step, run, following)
        return following

    async def _gcode(self, job: Job, step: Step, run: Run) -> Step | None:
        gcode = await self._check_gcode(job, step, run)
        run.feedback = gcode.feedback
        following = next_step(step, gcode.feedback.result)
        await self.store.gcode_checked(job, step, run, gcode, following)
        return following

    async def _select(
        self, job: Job, step: Step, card: TaskCard, feedback: Feedback | None
    ) -> ParameterSet:
        title = f"Заход {step.iteration}"
        await self.store.event(
            job.id, job.revision, "parameters.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is not None:
            return ParameterSet.model_validate(stored)
        return await self._quick(self.select, card, feedback)

    async def _check(self, job: Job, step: Step, parameter_set: ParameterSet) -> CheckResult:
        title = f"Проверка {step.iteration}"
        await self.store.event(
            job.id, job.revision, "validation.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is not None:
            return CheckResult.model_validate(stored)
        return await self._quick(self.check, parameter_set)

    async def _slice(self, job: Job, step: Step, parameter_set: ParameterSet) -> SliceReport:
        title = f"Нарезка {step.iteration}"
        await self.store.event(
            job.id, job.revision, "slicing.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is not None:
            return SliceReport.model_validate(stored)
        # A stored upload's key is its attachment id.
        models = {model.attachment_id: model.attachment_id for model in parameter_set.models}
        run = f"{job.id}-r{job.revision}-i{step.iteration}"
        return await self._watched(job, self.slicer.slice(run, parameter_set, models))

    async def _check_gcode(self, job: Job, step: Step, run: Run) -> GcodeCheck:
        title = f"Проверка {step.iteration}"
        await self.store.event(
            job.id, job.revision, "gcode.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is not None:
            return GcodeCheck.model_validate(stored)
        assert run.report is not None and run.report.gcode is not None
        try:
            return await self._quick(
                self.check_gcode, run.report.gcode, run.parameter_set, step.iteration
            )
        except TimeoutError:
            message = "Проверка G-code заняла слишком много времени"
            raise AppError(message, "gcode_timeout") from None

    async def _quick(self, work: Callable[..., T], *args: Any) -> T:
        """A pure step off the event loop of the worker, bounded by the step timeout."""
        return await asyncio.wait_for(asyncio.to_thread(work, *args), self.settings.timeout_seconds)

    async def _watched(self, job: Job, work: Awaitable[T]) -> T:
        """A long step ends as soon as the job is stopped or edited, not when it is done."""
        task = asyncio.ensure_future(work)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=WATCH_SECONDS)
                if done:
                    return task.result()
                await self.store.check(job.id, job.revision)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


class ParameterStore(JobStore):
    def __init__(self, uow: UowFactory, say: bool = True):
        super().__init__(uow)
        self.say = say

    async def result(self, job_id: str, revision: int, step: Step) -> dict[str, Any] | None:
        async with self.uow() as uow:
            return await uow.stage_results.get(job_id, revision, step)

    async def selected(
        self,
        job: Job,
        step: Step,
        run: Run,
        summary: ParametersSummary,
        following: Step | None,
    ) -> None:
        async with self.uow() as uow:
            current = await _locked(uow, job)
            await uow.stage_results.add(job.id, job.revision, step, run.parameter_set.published())
            # A new pass makes the slicing of the one before stale.
            current.parameters, current.result = summary, None
            await _event(uow, current, "parameters.completed", _selection_text(summary), step)
            await _advance(uow, current, following, run, self.say)
            await uow.commit()

    async def checked(self, job: Job, step: Step, run: Run, following: Step | None) -> None:
        assert run.check is not None
        async with self.uow() as uow:
            current = await _locked(uow, job)
            payload = run.check.model_dump(mode="json")
            await uow.stage_results.add(job.id, job.revision, step, payload)
            ok = run.check.feedback.result == "ok"
            status = "completed" if ok else "warning"
            await _event(uow, current, "validation.completed", _check_text(run.check), step, status)
            await _advance(uow, current, following, run, self.say)
            await uow.commit()

    async def sliced(self, job: Job, step: Step, run: Run, following: Step | None) -> None:
        report = run.report
        assert report is not None
        async with self.uow() as uow:
            current = await _locked(uow, job)
            await uow.stage_results.add(job.id, job.revision, step, report.model_dump(mode="json"))
            current.result = ResultSummary(
                iteration=step.iteration,
                sliced=report.status == "sliced",
                message=report.message,
                folder=report.folder if report.status == "sliced" else None,
                print_time_seconds=report.print_time_seconds,
                material_grams=report.material_grams,
                material_meters=report.material_meters,
            )
            clean = report.status == "sliced" and not report.clamped and not report.unsupported
            status = "completed" if clean else "warning"
            await _event(uow, current, "slicing.completed", _slice_text(report), step, status)
            await _advance(uow, current, following, run, self.say)
            await uow.commit()

    async def gcode_checked(
        self, job: Job, step: Step, run: Run, gcode: GcodeCheck, following: Step | None
    ) -> None:
        async with self.uow() as uow:
            current = await _locked(uow, job)
            await uow.stage_results.add(job.id, job.revision, step, gcode.model_dump(mode="json"))
            ok = gcode.result == "ok"
            assert current.result is not None
            current.result.gcode_check = "ok" if ok else "attention"
            status = "completed" if ok else "warning"
            await _event(uow, current, "gcode.completed", _gcode_text(gcode), step, status)
            await _advance(uow, current, following, run, self.say)
            await uow.commit()


def summarize(parameter_set: ParameterSet, catalog: Catalog) -> ParametersSummary:
    material = parameter_set.materials["0"].id
    profile = catalog.materials.get(material)
    quality = catalog.qualities.get(parameter_set.quality.quality_type)
    return ParametersSummary(
        iteration=parameter_set.iteration,
        printing_mode=MODE_NAMES[parameter_set.printing_mode.value],
        quality_type=quality.name if quality else parameter_set.quality.quality_type,
        material=profile.label if profile else material,
        changed_settings=len(parameter_set.settings),
        unsatisfied=len(parameter_set.unsatisfied),
        status=parameter_set.status,
    )


def _verdict(parameter_set: ParameterSet) -> Verdict | None:
    return "infeasible" if parameter_set.status == "infeasible" else None


def _started(job: Job) -> None:
    job.status = transition(job.status, Status.RUNNING)
    job.stage = "parameters"


def _card(job: Job) -> TaskCard:
    if job.card is None or job.card.revision != job.revision:
        raise AppError("Карточка задания не готова для подбора параметров", "card_missing")
    return job.card


async def _locked(uow: UnitOfWork, job: Job) -> Job:
    current = await uow.jobs.get(job.id, lock=True)
    ensure_current(current.revision, current.status, job.revision)
    return current


async def _advance(
    uow: UnitOfWork, job: Job, following: Step | None, run: Run, say: bool = True
) -> None:
    """The job waits at its next stage; after the last step the pipeline is done."""
    if following is not None:
        job.stage = following.stage
    else:
        await _complete(uow, job, run, say)
    await uow.jobs.save(job)


async def _complete(uow: UnitOfWork, job: Job, run: Run, say: bool = True) -> None:
    """The last step finishes the job; anything left unmet asks for the user's attention.

    ``say`` puts the outcome into the chat; a report written afterwards says it instead.
    """
    parameter_set, summary = run.parameter_set, job.parameters
    assert summary is not None
    check_ok = run.check is not None and run.check.feedback.result == "ok"
    clean = check_ok and parameter_set.status == "proposed" and not parameter_set.unsatisfied
    job.parameters = summary.model_copy(update={"check": "ok" if clean else "attention"})
    job.outcome = _outcome(clean, job.result)
    job.stage = "done"
    job.status = transition(job.status, Status.COMPLETED)
    text = _outcome_text(job.parameters, parameter_set, check_ok, job.result)
    if say:
        await uow.messages.add(
            Message(job_id=job.id, revision=job.revision, role="assistant", text=text)
        )
    status = "ok" if job.outcome == "ready" else "attention"
    await _event(uow, job, "pipeline.completed", text, None, status)


def _outcome(clean: bool, result: ResultSummary | None) -> Outcome:
    """Parameters that need attention come first, then whether the project was made."""
    if not clean:
        return "parameters_attention"
    if result is None or not result.sliced:
        return "not_sliced"
    return "ready" if result.gcode_check == "ok" else "attention"


async def _event(
    uow: UnitOfWork, job: Job, type: str, message: str, step: Step | None, status: str = "completed"
) -> None:
    data = _data(step) if step else {}
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type=type,
            status=status,
            message=message,
            data=data,
        )
    )


def _data(step: Step) -> dict[str, int]:
    return {"iteration": step.iteration}


def _selection_text(summary: ParametersSummary) -> str:
    changed = _count(summary.changed_settings, ("настройка", "настройки", "настроек"))
    return (
        f"Режим {summary.printing_mode}, профиль {summary.quality_type}, "
        f"материал {summary.material}, изменено {changed}"
    )


def _check_text(result: CheckResult) -> str:
    return _findings_text(
        sum(issue.level == "error" for issue in result.issues),
        sum(issue.level == "warning" for issue in result.issues),
    )


def _gcode_text(result: GcodeCheck) -> str:
    return _findings_text(
        sum(finding.level == "error" for finding in result.findings),
        sum(finding.level == "warning" for finding in result.findings),
    )


def _findings_text(errors: int, warnings: int) -> str:
    if not errors and not warnings:
        return "Замечаний нет"
    found = [
        _count(errors, ("ошибка", "ошибки", "ошибок")),
        _count(warnings, ("предупреждение", "предупреждения", "предупреждений")),
    ]
    return ", ".join(part for part in found if not part.startswith("0 "))


def _slice_text(report: SliceReport) -> str:
    if report.status != "sliced":
        return report.message
    notes = [report.message]
    if report.clamped:
        notes.append("слайсер изменил " + _count(len(report.clamped), _VALUES))
    if report.unsupported:
        notes.append("не применено " + _count(len(report.unsupported), _VALUES))
    estimate = _estimate(report.print_time_seconds, report.material_meters)
    return ", ".join(notes + ([estimate] if estimate else []))


_VALUES = ("значение", "значения", "значений")


def _estimate(seconds: int | None, meters: float | None) -> str:
    """The slicer's estimate of the print, as the chat shows it."""
    parts = []
    if seconds:
        hours, minutes = divmod(round(seconds / 60), 60)
        parts.append(f"печать {hours} ч {minutes} мин" if hours else f"печать {minutes} мин")
    if meters:
        parts.append(f"{meters:.1f}".replace(".", ",") + " м материала")
    return ", ".join(parts)


def _outcome_text(
    summary: ParametersSummary,
    parameter_set: ParameterSet,
    check_ok: bool,
    result: ResultSummary | None,
) -> str:
    """What the chat says at the end; details stay in the timeline rows."""
    details = _selection_text(summary)
    if parameter_set.status == "infeasible":
        return f"Подобрать параметры под все требования не получилось. {details}"
    if result is None or not result.sliced:
        reason = result.message if result else "Нарезка не проводилась"
        return f"Параметры подобраны, но проект не создан. {reason}. {details}"
    problem = _problem(parameter_set, check_ok, result)
    head = (
        f"Проект создан, но {problem}"
        if problem
        else "Проект готов, параметры и G-code прошли проверку"
    )
    estimate = _estimate(result.print_time_seconds, result.material_meters)
    return f"{head}. {details}" + (f", {estimate}" if estimate else "")


def _problem(parameter_set: ParameterSet, check_ok: bool, result: ResultSummary) -> str | None:
    """The first thing the user should look at in a project that was made."""
    if parameter_set.unsatisfied:
        return "выполнены не все требования"
    if not check_ok:
        return "проверка параметров оставила замечания"
    if result.gcode_check != "ok":
        return "проверка G-code оставила замечания"
    return None


def _count(number: int, forms: tuple[str, str, str]) -> str:
    """A Russian count: 1 настройка, 2 настройки, 5 настроек."""
    if 11 <= number % 100 <= 14 or number % 10 == 0 or number % 10 >= 5:
        return f"{number} {forms[2]}"
    return f"{number} {forms[0] if number % 10 == 1 else forms[1]}"
