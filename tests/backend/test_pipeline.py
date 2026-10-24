"""Parameter selection and its check after a ready card, against PostgreSQL.

Selection and the check are stand-ins here: the pipeline's own job is the order of the
steps, the revision guard, stop, retries and what the chat sees.
"""

import asyncio
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.backend.agents.runner import RunContext
from src.backend.agents.store import RunStore
from src.backend.domain.errors import AppError
from src.backend.domain.models import Status, TaskCard
from src.backend.domain.parameters import CheckResult, Feedback, Issue, ParameterSet
from src.backend.infrastructure.catalog import load_catalog
from src.backend.pipeline.parameters import ParameterPipeline, PipelineSettings

pytestmark = pytest.mark.integration
CATALOG = load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")
REASON = {"why": "профиль по умолчанию", "source": "default"}


def rid() -> str:
    return str(uuid.uuid4())


def proposal(card: TaskCard, feedback: Feedback | None, **changes) -> ParameterSet:
    iteration = 1 if feedback is None else 2
    return ParameterSet.model_validate(
        {
            "card_ref": {"job_id": card.job_id, "revision": card.revision},
            "iteration": iteration,
            "printer": "hte530v5.2.4",
            "printing_mode": {"value": "classic", **REASON},
            "quality": {"quality_type": "normal", **REASON},
            "materials": {"0": {"id": "enduse_petg", **REASON}},
            "settings": {"infill_sparse_density": {"value": 20 + 10 * iteration, **REASON}},
            "models": [
                {
                    "id": "m1",
                    "attachment_id": "att",
                    "extruder": 0,
                    "orientation_candidate": "o1",
                    "transform": {
                        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "position": [-9.5, 0.0, 15.0],
                        "scale": [1, 1, 1],
                    },
                    **REASON,
                }
            ],
            "status": "proposed",
            **changes,
        }
    )


def verdict(parameter_set: ParameterSet, ok: bool) -> CheckResult:
    if ok:
        return CheckResult(
            issues=[], feedback=Feedback(iteration=parameter_set.iteration, result="ok")
        )
    issue = Issue(
        level="error", where="settings.infill_sparse_density", kind="above_max", message="много"
    )
    constraint = {
        "id": "above_max.infill",
        "key": "infill_sparse_density",
        "op": "max",
        "value": 25,
    }
    feedback = Feedback(
        iteration=parameter_set.iteration, result="needs_changes", constraints=[constraint]
    )
    return CheckResult(issues=[issue], feedback=feedback)


class Steps:
    """Records what the pipeline asked for; the check passes from pass ``passing_from`` on."""

    def __init__(self, passing_from: int = 1):
        self.passing_from = passing_from
        self.selected: list[Feedback | None] = []
        self.checked: list[int] = []

    def select(self, card: TaskCard, feedback: Feedback | None) -> ParameterSet:
        self.selected.append(feedback)
        return proposal(card, feedback)

    def check(self, parameter_set: ParameterSet) -> CheckResult:
        self.checked.append(parameter_set.iteration)
        return verdict(parameter_set, parameter_set.iteration >= self.passing_from)


def pipeline(pg, steps, select=None, timeout: float = 5) -> ParameterPipeline:
    return ParameterPipeline(
        pg.uow, CATALOG, select or steps.select, steps.check, PipelineSettings(timeout)
    )


async def ready_job(http, pg) -> str:
    """A job whose stage one just handed a ready card over, as RunStore.finish does."""
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "x"})

    async def nothing(*args, **kwargs):
        return None

    ctx = RunContext(job_id=job_id, revision=1, run_id="r", check=nothing, event=nothing)
    card = TaskCard(job_id=job_id, revision=1, readiness="ready")
    await RunStore(pg.uow).finish(ctx, card, "Задание разобрано, передаю на подбор параметров")
    return job_id


async def job(pg, job_id: str):
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def rows(pg, sql: str, **params) -> list[dict]:
    async with pg.engine.connect() as connection:
        return [dict(r._mapping) for r in await connection.execute(text(sql), params)]


async def results(pg, job_id: str) -> list[tuple[int, str, int]]:
    found = await rows(
        pg,
        "SELECT revision, stage, iteration FROM stage_results WHERE job_id = :j "
        "ORDER BY revision, iteration, stage",
        j=job_id,
    )
    return [(r["revision"], r["stage"], r["iteration"]) for r in found]


async def events(pg, job_id: str) -> list[tuple[str, str]]:
    found = await rows(pg, "SELECT payload FROM events WHERE job_id = :j ORDER BY seq", j=job_id)
    return [(r["payload"]["type"], r["payload"]["status"]) for r in found]


async def test_a_ready_card_is_selected_checked_and_the_job_completes(pg, http):
    job_id = await ready_job(http, pg)
    queued = await rows(
        pg, "SELECT task_name, status FROM procrastinate_jobs WHERE queue_name = 'stage2'"
    )
    assert queued == [{"task_name": "stage2.select_parameters", "status": "todo"}]
    steps = Steps()
    await pipeline(pg, steps).run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.status, done.stage) == (Status.COMPLETED, "done")
    assert done.parameters.model_dump() == {
        "iteration": 1,
        "printing_mode": "3D",
        "quality_type": "Fine",
        "material": CATALOG.materials["enduse_petg"].label,
        "changed_settings": 1,
        "unsatisfied": 0,
        "status": "proposed",
        "check": "ok",
    }
    assert await results(pg, job_id) == [(1, "parameters", 1), (1, "validation", 1)]
    assert (await events(pg, job_id))[-5:] == [
        ("parameters.started", "running"),
        ("parameters.completed", "completed"),
        ("validation.started", "running"),
        ("validation.completed", "completed"),
        ("pipeline.completed", "ok"),
    ]
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    assert messages[-1]["payload"]["text"].startswith("Параметры подобраны и прошли проверку")


async def test_the_check_sends_the_selection_back_once(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps(passing_from=2)
    await pipeline(pg, steps).run(job_id, 1)
    assert steps.checked == [1, 2]
    assert (
        steps.selected[0] is None
        and steps.selected[1].constraints[0].key == "infill_sparse_density"
    )
    assert await results(pg, job_id) == [
        (1, "parameters", 1),
        (1, "validation", 1),
        (1, "parameters", 2),
        (1, "validation", 2),
    ]
    done = await job(pg, job_id)
    assert (done.status, done.parameters.iteration, done.parameters.check) == (
        Status.COMPLETED,
        2,
        "ok",
    )


async def test_problems_left_after_the_last_pass_ask_for_attention(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps(passing_from=3)
    await pipeline(pg, steps).run(job_id, 1)
    assert steps.checked == [1, 2]
    done = await job(pg, job_id)
    assert (done.status, done.parameters.check) == (Status.COMPLETED, "attention")
    assert ("pipeline.completed", "attention") in await events(pg, job_id)


async def test_an_unmet_requirement_asks_for_attention_even_when_the_check_passes(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def unmet(card, feedback):
        return proposal(card, feedback, unsatisfied=[{"requirement_id": "r", "why": "нет"}])

    await pipeline(pg, steps, select=unmet).run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.parameters.unsatisfied, done.parameters.check) == (1, "attention")
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    assert "выполнены не все требования" in messages[-1]["payload"]["text"]


async def test_a_stop_before_the_task_starts_keeps_the_job_stopped(pg, http):
    job_id = await ready_job(http, pg)
    await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
    steps = Steps()
    await pipeline(pg, steps).run(job_id, 1)
    assert (await job(pg, job_id)).status == Status.STOPPED
    assert steps.selected == [] and await results(pg, job_id) == []


async def test_a_stop_during_selection_ends_the_pipeline_before_the_check(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()
    loop = asyncio.get_running_loop()

    def stop_meanwhile(card, feedback):
        asyncio.run_coroutine_threadsafe(
            http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()}), loop
        ).result()
        return steps.select(card, feedback)

    await pipeline(pg, steps, select=stop_meanwhile).run(job_id, 1)
    assert (await job(pg, job_id)).status == Status.STOPPED
    assert steps.checked == [] and await results(pg, job_id) == []


async def test_an_edit_during_selection_leaves_the_new_revision_alone(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()
    loop = asyncio.get_running_loop()

    def edit_meanwhile(card, feedback):
        body = {"request_id": rid(), "text": "Допуск 0,1 мм"}
        asyncio.run_coroutine_threadsafe(
            http.post(f"/api/v1/jobs/{job_id}/messages", json=body), loop
        ).result()
        return steps.select(card, feedback)

    await pipeline(pg, steps, select=edit_meanwhile).run(job_id, 1)
    edited = await job(pg, job_id)
    assert (edited.revision, edited.status, edited.stage) == (2, Status.QUEUED, "understanding")
    assert edited.parameters is None and steps.checked == []
    assert await results(pg, job_id) == []


async def test_a_redelivered_task_reuses_the_steps_already_done(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def stuck_check(parameter_set):
        # The worker dies during the check: the selection is stored, the job still running.
        raise asyncio.CancelledError

    first = ParameterPipeline(pg.uow, CATALOG, steps.select, stuck_check, PipelineSettings(5))
    with pytest.raises(asyncio.CancelledError):
        await first.run(job_id, 1)
    assert (await job(pg, job_id)).status == Status.RUNNING
    assert await results(pg, job_id) == [(1, "parameters", 1)]
    await pipeline(pg, steps).run(job_id, 1)
    assert len(steps.selected) == 1 and steps.checked == [1]
    assert (await job(pg, job_id)).status == Status.COMPLETED


async def test_a_slow_step_fails_the_job_with_a_plain_message(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def slow(card, feedback):
        time.sleep(0.5)
        return steps.select(card, feedback)

    await pipeline(pg, steps, select=slow, timeout=0.1).run(job_id, 1)
    failed = await job(pg, job_id)
    assert (failed.status, failed.error) == (
        Status.FAILED,
        "Подбор параметров занял слишком много времени",
    )
    assert ("operation.failed", "failed") in await events(pg, job_id)


async def test_a_refused_card_fails_the_job_with_the_reason(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def refuse(card, feedback):
        raise AppError("Модель не помещается на стол", "does_not_fit")

    await pipeline(pg, steps, select=refuse).run(job_id, 1)
    failed = await job(pg, job_id)
    assert (failed.status, failed.error) == (Status.FAILED, "Модель не помещается на стол")


async def test_the_parameter_set_of_the_current_revision_is_served(pg, http, other):
    job_id = await ready_job(http, pg)
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 409
    await pipeline(pg, Steps(passing_from=2)).run(job_id, 1)
    served = (await http.get(f"/api/v1/jobs/{job_id}/parameters")).json()
    assert served["iteration"] == 2 and served["version"] == "0.2"
    assert (await other.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 404
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "y"})
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 409
