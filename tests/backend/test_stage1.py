"""Stage one end to end on PostgreSQL and real file processes; only the provider is scripted."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.backend.agents.schemas import Draft, Patch
from src.backend.agents.stage1 import apply_patch
from src.backend.domain.errors import AppError
from src.backend.domain.fields import FIELDS
from src.backend.domain.models import Status

from .fakes import ScriptedModel, reply

pytestmark = pytest.mark.integration
TEXT = "f1p1"
REQUIREMENTS = [
    {
        "key": "torque_nominal",
        "label": "Номинальный момент",
        "value": "25",
        "unit": "Нм",
        "sources": [{"source_id": TEXT, "quote": "Номинальный момент 25 Нм"}],
    },
    {
        "key": "torque_peak",
        "label": "Пиковый момент",
        "value": "75",
        "unit": "Нм",
        "conditions": "пик",
        "sources": [{"source_id": TEXT, "quote": "Пиковый момент 75 Нм"}],
    },
]
DRAFT = {"purpose": "Шестерня привода", "requirements": REQUIREMENTS}
EMPTY_READING = {"requirements": [], "questions": [], "unknowns": []}
# Every triage field cited from the task, so no early questions unless a test wants them.
FOUND = {
    "fields": [
        {"field": f.key, "value": "есть", "source_id": TEXT, "quote": "Номинальный момент 25 Нм"}
        for f in FIELDS
    ]
}
DEEP = {"interpreter", "analyst_loads", "analyst_environment", "analyst_production"}
AFTER = {"analyst_geometry", "consolidator", "discrepancies", "judge"}


def script(**overrides):
    base = {
        "triage": [reply(FOUND)],
        "interpreter": [reply(DRAFT)],
        "analyst_loads": [reply(EMPTY_READING)],
        "analyst_environment": [reply(EMPTY_READING)],
        "analyst_geometry": [reply(EMPTY_READING)],
        "analyst_production": [reply(EMPTY_READING)],
        "consolidator": [reply({})],
        "second_reading": [reply({"readings": []})],
        "discrepancies": [reply({"discrepancies": []})],
        "judge": [reply({"score": 0.9, "remarks": []})],
    }
    return ScriptedModel({**base, **overrides})


def rid() -> str:
    return str(uuid.uuid4())


async def job_with(http, *names: str) -> str:
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    for name in names:
        content = Path("tests/fixtures", name).read_bytes()
        response = await http.post(
            f"/api/v1/jobs/{job_id}/attachments",
            files={"file": (name, content)},
            data={"request_id": rid()},
        )
        assert response.status_code == 201, response.text
    start = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert start.status_code == 200, start.text
    return job_id


async def run(pg, job_id: str, model: ScriptedModel):
    pg.stage1.runner.model = model
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id)
    await pg.stage1.run(job_id, job.revision)
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def answer(http, job, answers: dict):
    response = await http.post(
        f"/api/v1/jobs/{job.id}/answers",
        json={"request_id": rid(), "expected_revision": job.revision, "answers": answers},
    )
    assert response.status_code == 200, response.text


async def rows(pg, sql: str, **params):
    async with pg.engine.connect() as connection:
        return [dict(r._mapping) for r in await connection.execute(text(sql), params)]


async def test_only_the_geometry_waits_for_the_stl_units(pg, http):
    model = script()
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), model)
    assert job.status == Status.WAITING
    assert [q.id for q in job.card.questions] == ["units"]
    assert "10 × 20 × 30" in job.card.questions[0].impact
    assert job.card.stl_analysis.report["file"]["sha256"] == job.card.stl_analysis.sha256
    assert set(model.requests) == {"triage", *DEEP}
    assert model.requests["triage"][0]["thinking"] is False


async def test_full_run_completes_and_queues_stage_two_with_the_card(pg, http):
    first = script()
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), first)
    await answer(http, job, {"units": "mm"})
    model = script()
    job = await run(pg, job.id, model)
    card = job.card
    assert job.status == Status.COMPLETED and card.readiness == "ready"
    assert [(r.key, r.verified) for r in card.requirements] == [
        ("torque_nominal", True),
        ("torque_peak", True),
    ]
    attachment = next(f for f in card.files if f.kind == "txt")
    assert card.requirements[0].sources[0].source_id == f"{attachment.id}:1"
    assert card.requirements[0].sources[0].method == "text"
    assert card.geometry.units == "mm" and card.geometry.extents == [10.0, 20.0, 30.0]
    assert card.verdict.passed and not card.verdict.reworked
    assert {q.id: q.answer for q in card.questions} == {"units": "mm"}
    # The answer reruns only what reads the scale or the answers; the rest comes from cache.
    assert set(model.requests) == AFTER
    reading = first.requests["interpreter"][0]["messages"][1]["content"][0]["text"]
    assert "Номинальный момент 25 Нм" in reading
    assert "<answers>" not in reading and "<stl>" not in reading
    shape = model.requests["analyst_geometry"][0]["messages"][1]["content"]
    assert '"units": "mm"' in shape[0]["text"] and "<stl_report>" in shape[0]["text"]
    assert shape[-1]["type"] == "image_url"
    assert model.requests["judge"][0]["budget"] == 6000
    queued = await rows(
        pg,
        "SELECT task_name, args FROM procrastinate_jobs WHERE queue_name = 'stage2'",
    )
    assert queued == [
        {
            "task_name": "stage2.select_parameters",
            "args": {"job_id": job.id, "revision": job.revision},
        }
    ]
    traces = await rows(pg, "SELECT agent, response FROM agent_calls WHERE job_id = :j", j=job.id)
    assert len(traces) == 9 and all(t["response"] for t in traces)
    exported = (await http.get(f"/api/v1/jobs/{job.id}/card")).json()
    assert exported == card.model_dump(mode="json")


async def test_without_stl_the_card_is_blocked_but_still_interpreted(pg, http):
    job = await run(pg, await job_with(http, "task.txt"), script())
    assert job.status == Status.WAITING
    assert job.card.blocked_actions["select_parameters"] == ["Нужна читаемая модель STL"]
    assert len(job.card.requirements) == 2


async def test_low_judge_score_gets_one_rework_then_blocks(pg, http):
    model = script(
        consolidator=[reply({}), reply({"purpose": "Шестерня привода натяжения троса"})],
        judge=[
            reply({"score": 0.3, "remarks": [{"severity": "major", "text": "Потерян пик"}]}),
            reply({"score": 0.5, "remarks": [{"severity": "critical", "text": "Пик не учтён"}]}),
        ],
    )
    job = await run(pg, await job_with(http, "task.txt"), model)
    assert len(model.requests["consolidator"]) == 2 and len(model.requests["judge"]) == 2
    assert {"discrepancies", "judge"} <= set(model.requests)
    rework = model.requests["consolidator"][1]["messages"][1]["content"][0]["text"]
    assert "<remarks>" in rework and "Потерян пик" in rework
    assert job.card.verdict.reworked and not job.card.verdict.passed
    assert (
        "Интерпретация не прошла итоговую проверку" in job.card.blocked_actions["select_parameters"]
    )
    assert (
        "Пик не учтён" in (await http.get(f"/api/v1/jobs/{job.id}")).json()["messages"][-1]["text"]
    )


async def test_unsupported_value_becomes_a_question_and_the_answer_replaces_it(pg, http):
    invented = {
        **REQUIREMENTS[0],
        "value": "250",
        "sources": [{"source_id": TEXT, "quote": "момент 250 Нм"}],
    }
    draft = {"purpose": "Шестерня", "requirements": [invented]}
    job = await run(pg, await job_with(http, "task.txt"), script(interpreter=[reply(draft)]))
    question = next(q for q in job.card.questions if q.kind == "verify")
    assert job.card.requirements[0].verified is False and question.options == ["250 Нм"]
    await answer(http, job, {question.id: "25 Нм"})
    job = await run(pg, job.id, script(interpreter=[reply(draft)]))
    requirement = job.card.requirements[0]
    assert (requirement.value, requirement.provenance, requirement.verified) == ("25", "user", True)
    assert requirement.sources[0].source_id == f"answer:{question.id}"


@pytest.mark.parametrize("reading,verified", [("25", True), ("26", False)])
async def test_image_values_need_an_agreeing_second_reading(pg, http, reading, verified):
    draft = {
        "purpose": "Шестерня",
        "requirements": [
            {
                "key": "torque_nominal",
                "label": "Номинальный момент",
                "value": "25",
                "unit": "Nm",
                "sources": [{"source_id": "f1p1", "quote": "Nominal torque 25 Nm"}],
            }
        ],
    }
    second = reply({"readings": [{"key": "torque_nominal", "value": reading, "unit": "Nm"}]})
    model = script(interpreter=[reply(draft)], second_reading=[second])
    job = await run(pg, await job_with(http, "scan.pdf"), model)
    requirement = job.card.requirements[0]
    assert requirement.verified is verified and requirement.sources[0].method == "vision"
    assert requirement.sources[0].artifact_id
    parts = model.requests["second_reading"][0]["messages"][1]["content"]
    assert "25" not in parts[0]["text"] and parts[-1]["type"] == "image_url"
    questions = [q for q in job.card.questions if q.kind == "verify"]
    assert (questions == []) is verified
    if not verified:
        assert questions[0].options == ["25 Nm", "26 Nm"]


async def test_conflicting_documents_go_to_the_user(pg, http):
    other = {
        **REQUIREMENTS[0],
        "value": "75",
        "sources": [{"source_id": TEXT, "quote": "Пиковый момент 75 Нм"}],
    }
    draft = {"purpose": "Шестерня", "requirements": [REQUIREMENTS[0], other]}
    job = await run(pg, await job_with(http, "task.txt"), script(interpreter=[reply(draft)]))
    question = next(q for q in job.card.questions if q.kind == "discrepancy")
    assert question.options == ["25 Нм", "75 Нм"] and job.status == Status.WAITING
    await answer(http, job, {question.id: "75 Нм"})
    job = await run(pg, job.id, script(interpreter=[reply(draft)]))
    assert [(r.value, [s.value for s in r.superseded]) for r in job.card.requirements] == [
        ("75", ["25"])
    ]


async def test_discrepancy_agent_questions_block_until_answered(pg, http):
    found = {
        "discrepancies": [
            {
                "kind": "tz_vs_stl",
                "requirement_key": "length",
                "title": "Длина в ТЗ 100 мм, в модели 30 мм",
                "options": ["Верно ТЗ", "Верна модель"],
            }
        ]
    }
    job = await run(pg, await job_with(http, "task.txt"), script(discrepancies=[reply(found)]))
    question = next(q for q in job.card.questions if q.kind == "discrepancy")
    assert question.id.startswith("tz_vs_stl.") and question.blocking
    assert question.title in job.card.blocked_actions["select_parameters"]


async def test_newer_revision_discards_the_running_result(pg, http):
    job_id = await job_with(http, "task.txt")

    async def edit_meanwhile(messages):
        await http.post(
            f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "Правка"}
        )
        return reply(DRAFT)

    job = await run(pg, job_id, script(interpreter=[edit_meanwhile]))
    # Only the early questions of the old revision stay; its final card is never written.
    assert job.status == Status.QUEUED and job.card.revision < job.revision
    assert job.card.verdict is None and job.phase is None


async def test_stop_takes_effect_at_the_next_safe_point(pg, http):
    job_id = await job_with(http, "task.txt")

    async def stop_meanwhile(messages):
        await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
        return reply(DRAFT)

    model = script(interpreter=[stop_meanwhile])
    job = await run(pg, job_id, model)
    assert job.status == Status.STOPPED and "consolidator" not in model.requests


async def test_provider_failure_keeps_files_and_reports_a_plain_message(pg, http):
    failure = AppError("Модель не отвечает, попробуйте позже", "model_unavailable", 503)
    job = await run(pg, await job_with(http, "task.txt"), script(interpreter=[failure]))
    assert job.status == Status.FAILED and job.error == "Модель не отвечает, попробуйте позже"
    snapshot = (await http.get(f"/api/v1/jobs/{job.id}")).json()
    assert snapshot["attachments"][0]["status"] == "completed"


async def test_broken_file_blocks_selection_but_not_interpretation(pg, http):
    job = await run(pg, await job_with(http, "task.txt", "corrupt.pdf"), script())
    assert job.status == Status.WAITING
    assert any("corrupt.pdf" in r for r in job.card.blocked_actions["select_parameters"])
    assert len(job.card.requirements) == 2


async def test_unexpected_error_marks_the_job_failed(pg, http):
    job = await run_failing(pg, await job_with(http, "task.txt"))
    assert job.status == Status.FAILED and job.error.startswith("Внутренняя ошибка")


async def run_failing(pg, job_id: str):
    with pytest.raises(KeyError):
        await run(pg, job_id, script(interpreter=[KeyError("bug")]))
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def test_files_attached_during_a_run_keep_the_card_from_stage_two(pg, http):
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), script())
    await answer(http, job, {"units": "mm"})

    async def attach_meanwhile(messages):
        content = Path("tests/fixtures/task.docx").read_bytes()
        await http.post(
            f"/api/v1/jobs/{job.id}/attachments",
            files={"file": ("extra.docx", content)},
            data={"request_id": rid()},
        )
        return reply({})

    job = await run(pg, job.id, script(consolidator=[attach_meanwhile]))
    assert job.files_changed and job.status == Status.WAITING
    assert job.card.readiness == "ready" and job.next_stage == "not_ready"
    assert await rows(pg, "SELECT id FROM procrastinate_jobs WHERE queue_name = 'stage2'") == []


async def test_triage_questions_are_published_before_the_deep_reading(pg, http):
    job_id = await job_with(http, "task.txt")
    seen = {}

    async def look_meanwhile(messages):
        snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
        seen["status"] = snapshot["job"]["status"]
        seen["questions"] = [q["id"] for q in snapshot["job"]["card"]["questions"]]
        return reply(DRAFT)

    empty = reply({"fields": [], "questions": [{"field": "loads", "options": ["Нет", "Есть"]}]})
    job = await run(pg, job_id, script(triage=[empty], interpreter=[look_meanwhile]))
    assert seen["status"] == "running"
    assert seen["questions"][:2] == ["purpose", "field.geometry_editable"]
    assert len(seen["questions"]) == 5
    asked = {q.id: q for q in job.card.questions}
    # Open triage questions the consolidation did not repeat are gone, blocking ones stay.
    assert "field.loads" not in asked and job.card.purpose == "Шестерня привода"
    assert "purpose" not in asked and asked["field.geometry_editable"].blocking


async def test_answers_during_the_deep_reading_join_without_a_restart(pg, http):
    job_id = await job_with(http, "task.txt")
    empty = reply({"fields": [], "questions": []})

    async def answer_meanwhile(messages):
        snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
        response = await http.post(
            f"/api/v1/jobs/{job_id}/answers",
            json={
                "request_id": rid(),
                "expected_revision": snapshot["job"]["revision"],
                "answers": {"field.geometry_editable": "Печать строго по модели"},
            },
        )
        assert response.status_code == 200, response.text
        return reply(DRAFT)

    model = script(triage=[empty], interpreter=[answer_meanwhile])
    job = await run(pg, job_id, model)
    assert job.revision == 1 and job.status == Status.WAITING
    answered = {q.id: q.answer for q in job.card.questions}
    assert answered["field.geometry_editable"] == "Печать строго по модели"
    consolidation = model.requests["consolidator"][0]["messages"][1]["content"][0]["text"]
    assert "Печать строго по модели" in consolidation
    queued = await rows(
        pg, "SELECT args FROM procrastinate_jobs WHERE args->>'job_id' = :j", j=job_id
    )
    assert len(queued) == 1


def test_patch_edits_the_draft_by_requirement_id():
    draft = Draft.model_validate(DRAFT)
    patch = Patch.model_validate(
        {
            "change": [
                {**REQUIREMENTS[0], "id": "r1", "value": "26"},
                {"id": "r9", "key": "x", "value": "1"},
            ],
            "remove": [{"id": "r2", "reason": "нет в источниках"}],
            "add": [{"key": "temperature_max", "value": "70", "unit": "C"}],
            "questions": [{"title": "Какие нагрузки", "field": "loads"}],
        }
    )
    result = apply_patch(draft, patch, [])
    assert [(r.key, r.value) for r in result.requirements] == [
        ("torque_nominal", "26"),
        ("temperature_max", "70"),
    ]
    assert result.purpose == "Шестерня привода" and result.questions[0].field == "loads"
    kept = apply_patch(draft, Patch(), draft.questions)
    assert kept.requirements == draft.requirements


async def test_triage_names_the_chat_unless_the_user_renamed_it(pg, http):
    titled = reply({**FOUND, "title": "Шестерня привода троса"})
    job = await run(pg, await job_with(http, "task.txt"), script(triage=[titled]))
    assert job.title == "Шестерня привода троса"
    job_id = await job_with(http, "task.txt")
    await http.post(f"/api/v1/jobs/{job_id}/rename", json={"request_id": rid(), "title": "Моё"})
    job = await run(pg, job_id, script(triage=[titled]))
    assert job.title == "Моё"


def test_triage_quotes_may_join_verbatim_fragments_with_an_ellipsis():
    from src.backend.agents.schemas import TriageField
    from src.backend.agents.stage1 import _cited
    from src.backend.domain.models import Source

    from .fakes import context

    ctx = context()
    ctx.sources["f1p1"] = Source(
        id="f1p1", ref="x", kind="document", text="Номинальный момент 25 Нм. Режим старт-стоп."
    )

    def cited(quote: str) -> bool:
        return _cited(TriageField(field="loads", source_id="f1p1", quote=quote), ctx)

    assert cited("Номинальный момент 25 Нм… Режим старт-стоп")
    assert cited("Режим старт-стоп. Номинальный момент 25 Нм.")
    assert not cited("Номинальный момент 30 Нм... Режим старт-стоп")
    assert not cited("...")


async def test_a_sharper_question_about_a_field_keeps_its_id(pg, http):
    empty = reply({"fields": [], "questions": []})
    sharper = {
        "questions": [
            {
                "title": "Работает на сухую или со смазкой",
                "field": "environment",
                "blocking": False,
            },
            {"title": "Можно ли утолщать зубья", "field": "geometry_editable"},
        ]
    }
    job = await run(
        pg, await job_with(http, "task.txt"), script(triage=[empty], consolidator=[reply(sharper)])
    )
    asked = {q.id: q.title for q in job.card.questions}
    assert asked["field.environment"] == "Работает на сухую или со смазкой"
    assert asked["field.geometry_editable"] == "Можно ли утолщать зубья"
