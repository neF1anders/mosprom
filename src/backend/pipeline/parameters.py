"""Parameter selection and its check for a ready card, in one task.

Both steps are deterministic and take well under a second, so they run back to back
instead of handing over through the queue: selection, its check and, if the check asks for
changes, one more selection and check. Each step commits its result, event and summary
under the revision guard, so the chat follows step by step and a stop or an edit takes
effect between steps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.catalog import Catalog
from ..domain.errors import AppError, OperationCancelled
from ..domain.models import Event, Job, Message, ParametersSummary, Status, TaskCard
from ..domain.parameters import CheckResult, Feedback, ParameterSet
from ..domain.pipeline import FIRST_STEP, Step, next_step
from ..domain.transitions import transition
from ..ports.persistence import UnitOfWork, UowFactory
from .store import JobStore, ensure_current

Select = Callable[[TaskCard, Feedback | None], ParameterSet]
Check = Callable[[ParameterSet], CheckResult]
MODE_NAMES = {"classic": "3D", "cylindrical": "5D Spiral", "cylindrical_full": "5D"}


@dataclass(frozen=True)
class PipelineSettings:
    timeout_seconds: float


class ParameterPipeline:
    def __init__(
        self,
        uow: UowFactory,
        catalog: Catalog,
        select: Select,
        check: Check,
        settings: PipelineSettings,
    ):
        self.store = ParameterStore(uow)
        self.catalog, self.select, self.check = catalog, select, check
        self.settings = settings

    async def run(self, job_id: str, revision: int) -> None:
        try:
            await asyncio.wait_for(self._run(job_id, revision), self.settings.timeout_seconds)
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
        parameter_set: ParameterSet | None = None
        feedback: Feedback | None = None
        while step is not None:
            await self.store.check(job_id, revision)
            if step.stage == "parameters":
                parameter_set = await self._select(job, step, card, feedback)
                step = next_step(step)
            else:
                assert parameter_set is not None
                feedback = await self._check(job, step, parameter_set)
                step = next_step(step, feedback.result)

    async def _select(
        self, job: Job, step: Step, card: TaskCard, feedback: Feedback | None
    ) -> ParameterSet:
        title = f"Заход {step.iteration}"
        await self.store.event(
            job.id, job.revision, "parameters.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is None:
            parameter_set = await asyncio.to_thread(self.select, card, feedback)
        else:
            parameter_set = ParameterSet.model_validate(stored)
        summary = summarize(parameter_set, self.catalog)
        await self.store.selected(job, step, parameter_set, summary)
        return parameter_set

    async def _check(self, job: Job, step: Step, parameter_set: ParameterSet) -> Feedback:
        title = f"Проверка {step.iteration}"
        await self.store.event(
            job.id, job.revision, "validation.started", title, iteration=step.iteration
        )
        stored = await self.store.result(job.id, job.revision, step)
        if stored is None:
            result = await asyncio.to_thread(self.check, parameter_set)
        else:
            result = CheckResult.model_validate(stored)
        last = next_step(step, result.feedback.result) is None
        await self.store.checked(job, step, parameter_set, result, last)
        return result.feedback


class ParameterStore(JobStore):
    async def result(self, job_id: str, revision: int, step: Step) -> dict[str, Any] | None:
        async with self.uow() as uow:
            return await uow.stage_results.get(job_id, revision, step)

    async def selected(
        self, job: Job, step: Step, parameter_set: ParameterSet, summary: ParametersSummary
    ) -> None:
        async with self.uow() as uow:
            current = await _locked(uow, job)
            await uow.stage_results.add(job.id, job.revision, step, parameter_set.published())
            current.stage, current.parameters = "validation", summary
            await uow.jobs.save(current)
            await _event(uow, current, "parameters.completed", _selection_text(summary), step)
            await uow.commit()

    async def checked(
        self, job: Job, step: Step, parameter_set: ParameterSet, result: CheckResult, last: bool
    ) -> None:
        async with self.uow() as uow:
            current = await _locked(uow, job)
            await uow.stage_results.add(job.id, job.revision, step, result.model_dump(mode="json"))
            summary = current.parameters
            assert summary is not None
            ok = result.feedback.result == "ok"
            text = _check_text(result)
            status = "completed" if ok else "warning"
            await _event(uow, current, "validation.completed", text, step, status)
            if last:
                await _complete(uow, current, summary, parameter_set, ok)
            else:
                current.stage = "parameters"
            await uow.jobs.save(current)
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


async def _complete(
    uow: UnitOfWork,
    job: Job,
    summary: ParametersSummary,
    parameter_set: ParameterSet,
    check_ok: bool,
) -> None:
    """The last step finishes the job; anything left unmet asks for the user's attention."""
    clean = check_ok and parameter_set.status == "proposed" and not parameter_set.unsatisfied
    final = summary.model_copy(update={"check": "ok" if clean else "attention"})
    job.parameters, job.stage = final, "done"
    job.status = transition(job.status, Status.COMPLETED)
    text = _outcome_text(final, parameter_set, check_ok)
    await uow.messages.add(
        Message(job_id=job.id, revision=job.revision, role="assistant", text=text)
    )
    await _event(uow, job, "pipeline.completed", text, None, final.check)


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
    return (
        f"Режим {summary.printing_mode}, профиль {summary.quality_type}, "
        f"материал {summary.material}, изменено настроек {summary.changed_settings}"
    )


def _check_text(result: CheckResult) -> str:
    errors = sum(issue.level == "error" for issue in result.issues)
    warnings = sum(issue.level == "warning" for issue in result.issues)
    if not errors and not warnings:
        return "Замечаний нет"
    return f"Ошибок {errors}, предупреждений {warnings}"


def _outcome_text(summary: ParametersSummary, parameter_set: ParameterSet, check_ok: bool) -> str:
    """What the chat says at the end; details stay in the timeline rows."""
    details = _selection_text(summary)
    if parameter_set.status == "infeasible":
        return f"Подобрать параметры под все требования не получилось. {details}"
    if parameter_set.unsatisfied:
        unmet = len(parameter_set.unsatisfied)
        return f"Параметры подобраны, но не выполнено требований {unmet}. {details}"
    if not check_ok:
        return f"Параметры подобраны, но проверка оставила замечания. {details}"
    return f"Параметры подобраны и прошли проверку. {details}"
