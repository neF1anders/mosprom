"""Selection, its check, slicing and the G-code check after a ready card, against PostgreSQL.

The steps are stand-ins here: the pipeline's own job is the order of the steps, the
revision guard, stop, retries and what the chat sees. The last tests run the real steps
with the stand-in of the STE Slicer plugin.
"""

import asyncio
import time
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text

from scripts.fake_ste_slicer import FakeSlicer
from src.backend.agents.runner import RunContext
from src.backend.agents.store import RunStore
from src.backend.domain.errors import AppError
from src.backend.domain.models import Requirement, Status, StlAnalysis, TaskCard
from src.backend.domain.parameters import CheckResult, Exclusion, Feedback, Issue, ParameterSet
from src.backend.domain.projects import part_name
from src.backend.domain.results import folder_name
from src.backend.domain.slicing import GcodeCheck, GcodeFinding, SliceReport
from src.backend.infrastructure.catalog import load_catalog
from src.backend.pipeline.parameters import ParameterPipeline, PipelineSettings
from src.backend.services.commands import changed
from src.mesh_analysis import analyze_stl

pytestmark = pytest.mark.integration
CATALOG = load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")
REASON = {"why": "профиль по умолчанию", "source": "default"}


def rid() -> str:
    return str(uuid.uuid4())


def proposal(card: TaskCard, feedback: Feedback | None, **changes) -> ParameterSet:
    iteration = 1 if feedback is None else feedback.iteration + 1
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


def gcode_verdict(iteration: int, ok: bool) -> GcodeCheck:
    if ok:
        return GcodeCheck(
            result="ok", findings=[], feedback=Feedback(iteration=iteration, result="ok")
        )
    finding = GcodeFinding(id="G1", kind="content", level="error", message="модель за столом")
    exclude = [Exclusion(type="orientation", candidate="o1", reason="модель за столом")]
    feedback = Feedback(iteration=iteration, result="needs_changes", exclude=exclude)
    return GcodeCheck(result="needs_changes", findings=[finding], feedback=feedback)


class Steps:
    """Records what the pipeline asked for; the check passes from pass ``passing_from`` on
    and the G-code check from pass ``gcode_from`` on."""

    def __init__(self, passing_from: int = 1, gcode_from: int = 1, slicer: str = "sliced"):
        self.passing_from, self.gcode_from, self.slicer = passing_from, gcode_from, slicer
        self.selected: list[Feedback | None] = []
        self.checked: list[int] = []
        self.sliced: list[tuple[str, int, dict]] = []
        self.gcode: list[str] = []

    def select(self, card: TaskCard, feedback: Feedback | None) -> ParameterSet:
        self.selected.append(feedback)
        return proposal(card, feedback)

    def check(self, parameter_set: ParameterSet) -> CheckResult:
        self.checked.append(parameter_set.iteration)
        return verdict(parameter_set, parameter_set.iteration >= self.passing_from)

    async def slice(self, run: str, parameter_set: ParameterSet, models: dict) -> SliceReport:
        self.sliced.append((run, parameter_set.iteration, models))
        if self.slicer != "sliced":
            message = "STE Slicer с плагином AI Assistant не запущен"
            return SliceReport(status=self.slicer, message=message)
        return SliceReport(
            status="sliced",
            message="G-code и проект сохранены",
            gcode=f"{run}.gcode",
            project=f"{run}.3mf",
            folder=r"C:\STE_AIAssistant\mosprom",
            print_time_seconds=3720,
            material_meters=1.5,
        )

    def check_gcode(self, key: str, parameter_set: ParameterSet, iteration: int) -> GcodeCheck:
        self.gcode.append(key)
        return gcode_verdict(iteration, iteration >= self.gcode_from)


def pipeline(pg, steps, select=None, timeout: float = 5, slicer=None):
    return ParameterPipeline(
        pg.uow,
        CATALOG,
        select or steps.select,
        steps.check,
        slicer or steps,
        steps.check_gcode,
        PipelineSettings(timeout),
    )


async def ready_job(http, pg, **card) -> str:
    """A job whose stage one just handed a ready card over, as RunStore.finish does."""
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    # The assistant started the work, as its tool does.
    async with pg.uow() as uow:
        await changed(uow, await uow.jobs.get(job_id, lock=True), "Новый проект", start=True)
        await uow.commit()

    async def nothing(*args, **kwargs):
        return None

    ctx = RunContext(job_id=job_id, revision=1, run_id="r", check=nothing, event=nothing)
    card = TaskCard(job_id=job_id, revision=1, readiness="ready", **card)
    await RunStore(pg.uow).finish(ctx, card, "Задание разобрано, передаю на подбор параметров")
    return job_id


async def revise(pg, job_id: str) -> None:
    """A correction the assistant applied: a new revision with its stage-one task."""
    async with pg.uow() as uow:
        await changed(uow, await uow.jobs.get(job_id, lock=True), "Правка принята", correction=True)
        await uow.commit()


async def job(pg, job_id: str):
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def rows(pg, sql: str, **params) -> list[dict]:
    async with pg.engine.connect() as connection:
        return [dict(r._mapping) for r in await connection.execute(text(sql), params)]


ORDER = ("parameters", "validation", "slicing", "gcode")


async def results(pg, job_id: str) -> list[tuple[int, str, int]]:
    """Stored steps in the order they run."""
    found = await rows(
        pg, "SELECT revision, stage, iteration FROM stage_results WHERE job_id = :j", j=job_id
    )
    steps = [(r["revision"], r["stage"], r["iteration"]) for r in found]
    return sorted(steps, key=lambda s: (s[0], s[2], ORDER.index(s[1])))


def full_pass(iteration: int) -> list[tuple[int, str, int]]:
    return [(1, stage, iteration) for stage in ORDER]


async def events(pg, job_id: str) -> list[tuple[str, str]]:
    found = await rows(pg, "SELECT payload FROM events WHERE job_id = :j ORDER BY seq", j=job_id)
    return [(r["payload"]["type"], r["payload"]["status"]) for r in found]


async def test_a_ready_card_goes_through_every_step_to_a_project(pg, http):
    job_id = await ready_job(http, pg)
    queued = await rows(
        pg, "SELECT task_name, status FROM procrastinate_jobs WHERE queue_name = 'stage2'"
    )
    assert queued == [{"task_name": "stage2.select_parameters", "status": "todo"}]
    steps = Steps()
    await pipeline(pg, steps).run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.status, done.stage, done.outcome) == (Status.COMPLETED, "done", "ready")
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
    assert done.result.model_dump() == {
        "iteration": 1,
        "sliced": True,
        "message": "G-code и проект сохранены",
        "gcode_check": "ok",
        "folder": r"C:\STE_AIAssistant\mosprom",
        "print_time_seconds": 3720,
        "material_grams": None,
        "material_meters": 1.5,
    }
    assert steps.sliced == [(f"{job_id}-r1-i1", 1, {"att": "att"})]
    assert steps.gcode == [f"{job_id}-r1-i1.gcode"]
    assert await results(pg, job_id) == full_pass(1)
    assert (await events(pg, job_id))[-9:] == [
        ("parameters.started", "running"),
        ("parameters.completed", "completed"),
        ("validation.started", "running"),
        ("validation.completed", "completed"),
        ("slicing.started", "running"),
        ("slicing.completed", "completed"),
        ("gcode.started", "running"),
        ("gcode.completed", "completed"),
        ("pipeline.completed", "ok"),
    ]
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    assert messages[-1]["payload"]["text"] == (
        "Проект готов, параметры и G-code прошли проверку. Режим 3D, профиль Fine, "
        f"материал {CATALOG.materials['enduse_petg'].label}, изменено 1 настройка, "
        "печать 1 ч 2 мин, 1,5 м материала"
    )


async def test_the_check_sends_the_selection_back_once(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps(passing_from=2)
    await pipeline(pg, steps).run(job_id, 1)
    assert steps.checked == [1, 2]
    assert (
        steps.selected[0] is None
        and steps.selected[1].constraints[0].key == "infill_sparse_density"
    )
    assert await results(pg, job_id) == [(1, "parameters", 1), (1, "validation", 1), *full_pass(2)]
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
    # The last pass is sliced with what is left, so the user still gets a project.
    assert [iteration for _, iteration, _ in steps.sliced] == [2]
    done = await job(pg, job_id)
    assert (done.status, done.parameters.check) == (Status.COMPLETED, "attention")
    assert done.result.sliced and done.result.gcode_check == "ok"
    # The chat shows the server's verdict: the parameters ask for attention first.
    assert done.outcome == "parameters_attention"
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
        asyncio.run_coroutine_threadsafe(revise(pg, job_id), loop).result()
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

    first = ParameterPipeline(
        pg.uow, CATALOG, steps.select, stuck_check, steps, steps.check_gcode, PipelineSettings(5)
    )
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


async def test_the_parameter_set_of_the_current_work_is_served(pg, http, other):
    job_id = await ready_job(http, pg)
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 409
    await pipeline(pg, Steps(passing_from=2)).run(job_id, 1)
    served = (await http.get(f"/api/v1/jobs/{job_id}/parameters")).json()
    assert served["iteration"] == 2 and served["version"] == "0.2"
    assert (await other.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 404
    # A new revision alone keeps the finished project; only work started on it replaces the set.
    await revise(pg, job_id)
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).json() == served

    async def nothing(*args, **kwargs):
        return None

    ctx = RunContext(job_id=job_id, revision=2, run_id="r", check=nothing, event=nothing)
    await RunStore(pg.uow).begin(ctx)
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 409


async def real_job(http, pg) -> str:
    stl = Path("tests/fixtures/box.stl")
    pg.files.path("att").write_bytes(stl.read_bytes())
    report = analyze_stl(stl, units="mm")
    analysis = StlAnalysis(attachment_id="att", sha256=report["file"]["sha256"], report=report)
    return await ready_job(
        http,
        pg,
        purpose="Корпус датчика",
        requirements=[
            Requirement(key="service_temp_max_c", value="80", unit="°C", verified=True),
            Requirement(key="load_bearing", value="cyclic", verified=True),
        ],
        stl_analysis=analysis,
    )


@pytest.fixture
def plugin(pg):
    fake = FakeSlicer(pg.settings.slicer_folder)
    fake.start()
    yield fake
    fake.stop()


async def test_the_real_steps_and_the_plugin_stand_in_make_a_project(pg, http, plugin):
    job_id = await real_job(http, pg)
    assert (await http.get(f"/api/v1/jobs/{job_id}/result/project")).status_code == 409
    await pg.pipeline.run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.status, done.stage) == (Status.COMPLETED, "done")
    served = ParameterSet.model_validate(
        (await http.get(f"/api/v1/jobs/{job_id}/parameters")).json()
    )
    assert served.card_ref.job_id == job_id and served.printer == "hte530v5.2.4"
    assert served.materials["0"].id in pg.catalog.materials
    # The selected material has to hold 80 °C: the check of the requirement passed.
    temperature = next(c for c in served.materials["0"].checks if c.key == "service_temp_max_c")
    assert temperature.status in ("ok", "unknown")
    assert done.parameters.check in ("ok", "attention")
    # The stand-in got the set as it was selected, and its G-code passed the real check.
    assert ("set_material", {"material_id": served.materials["0"].id}) in [
        (name, {k: v for k, v in args.items() if k != "reason"}) for name, args in plugin.calls
    ]
    assert done.result.sliced and done.result.gcode_check == "ok", done.result
    run = pg.settings.slicer_folder / "mosprom" / f"{job_id}-r1-i1"
    gcode = await http.get(f"/api/v1/jobs/{job_id}/result/gcode")
    assert gcode.status_code == 200 and gcode.content == (run / "result.gcode").read_bytes()
    assert "result.gcode" in gcode.headers["content-disposition"]
    project = await http.get(f"/api/v1/jobs/{job_id}/result/project")
    assert project.content == (run / "project.3mf").read_bytes()
    # The user keeps the project in a folder of its own, named after the part, with the
    # report and a picture of the chat; the chat and the report point to that folder.
    kept = pg.settings.slicer_folder / "Результаты" / folder_name(part_name(done))
    assert done.result.folder == str(kept)
    names = sorted(p.name for p in kept.iterdir())
    assert names == ["chat_01.png", "project.3mf", "report.md", "result.gcode"]
    assert (kept / "result.gcode").read_bytes() == gcode.content
    assert (kept / "project.3mf").read_bytes() == project.content
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    report = messages[-1]["payload"]
    assert report["kind"] == "report"
    assert f"Проект лежит в папке {kept}" in report["text"]
    assert (kept / "report.md").read_text() == report["text"]
    with Image.open(kept / "chat_01.png") as picture:
        assert picture.format == "PNG" and picture.width == 1080


async def test_without_a_running_slicer_the_parameters_stay_and_the_chat_says_why(pg, http):
    job_id = await real_job(http, pg)
    await pg.pipeline.run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.status, done.stage) == (Status.COMPLETED, "done")
    assert done.result.sliced is False and done.result.gcode_check == "pending"
    assert (await http.get(f"/api/v1/jobs/{job_id}/parameters")).status_code == 200
    assert (await http.get(f"/api/v1/jobs/{job_id}/result/gcode")).status_code == 409
    assert await results(pg, job_id) == full_pass(1)[:3]
    assert ("slicing.completed", "warning") in await events(pg, job_id)
    assert ("pipeline.completed", "attention") in await events(pg, job_id)
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    # The report closes the project; without its model the template says the same.
    report = messages[-1]["payload"]
    assert report["kind"] == "report"
    assert report["text"].startswith("Параметры подобраны, но проект не создан")
    assert "STE Slicer с плагином AI Assistant не запущен" in report["text"]
    # Nothing was sliced, yet the request keeps its folder with the report and the chat.
    kept = pg.settings.slicer_folder / "Результаты" / folder_name(part_name(done))
    assert sorted(p.name for p in kept.iterdir()) == ["chat_01.png", "report.md"]
    assert "Проект лежит в папке" not in report["text"]


async def test_the_gcode_check_sends_the_selection_back_once(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps(gcode_from=2)
    await pipeline(pg, steps).run(job_id, 1)
    assert steps.selected[0] is None
    assert [e.candidate for e in steps.selected[1].exclude] == ["o1"]
    assert await results(pg, job_id) == full_pass(1) + full_pass(2)
    done = await job(pg, job_id)
    assert (done.result.iteration, done.result.gcode_check) == (2, "ok")


async def test_both_checks_share_the_one_return_to_selection(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps(passing_from=2, gcode_from=3)
    await pipeline(pg, steps).run(job_id, 1)
    assert len(steps.selected) == 2 and [i for _, i, _ in steps.sliced] == [2]
    done = await job(pg, job_id)
    assert (done.status, done.result.gcode_check) == (Status.COMPLETED, "attention")
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    assert messages[-1]["payload"]["text"].startswith(
        "Проект создан, но проверка G-code оставила замечания"
    )


async def test_a_stop_during_slicing_ends_it_without_waiting_for_the_slicer(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    class Slow:
        async def slice(self, run, parameter_set, models):
            await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
            await asyncio.sleep(30)

    started = time.monotonic()
    await pipeline(pg, steps, slicer=Slow()).run(job_id, 1)
    assert time.monotonic() - started < 5
    assert (await job(pg, job_id)).status == Status.STOPPED
    assert steps.gcode == [] and (1, "slicing", 1) not in await results(pg, job_id)


async def test_a_redelivered_task_does_not_slice_again(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def lost(key, parameter_set, iteration):
        # The worker dies during the G-code check, after the slicing was stored.
        raise asyncio.CancelledError

    first = ParameterPipeline(
        pg.uow, CATALOG, steps.select, steps.check, steps, lost, PipelineSettings(5)
    )
    with pytest.raises(asyncio.CancelledError):
        await first.run(job_id, 1)
    await pipeline(pg, steps).run(job_id, 1)
    assert len(steps.sliced) == 1 and steps.gcode == [f"{job_id}-r1-i1.gcode"]
    assert (await job(pg, job_id)).status == Status.COMPLETED


async def test_an_infeasible_selection_ends_the_pipeline_without_a_check(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()

    def too_big(card, feedback):
        why = "габариты не помещаются ни в один режим"
        unmet = [{"requirement_id": "GEOMETRY", "why": why}]
        return proposal(card, feedback, status="infeasible", unsatisfied=unmet)

    await pipeline(pg, steps, select=too_big).run(job_id, 1)
    done = await job(pg, job_id)
    assert (done.status, done.parameters.check) == (Status.COMPLETED, "attention")
    assert steps.checked == [] and await results(pg, job_id) == [(1, "parameters", 1)]
    messages = await rows(
        pg, "SELECT payload FROM messages WHERE job_id = :j ORDER BY seq", j=job_id
    )
    assert messages[-1]["payload"]["text"].startswith("Подобрать параметры под все требования")
