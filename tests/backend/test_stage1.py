"""Stage one end to end on PostgreSQL and real file processes; only the provider is scripted."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.backend.domain.errors import AppError
from src.backend.domain.models import Status
from src.backend.services.commands import changed

from .fakes import ScriptedModel, call, reply

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
    # The same property as a filled code; the code wins and this one is dropped.
    {
        "key": "service_temp_max_c",
        "value": "70",
        "unit": "C",
        "sources": [{"source_id": TEXT, "quote": "Температура от 10 до 70 C"}],
    },
]
CODES = {
    "service_temp_max_c": {
        "value": "от 10 до 70",
        "unit": "C",
        "label": "Рабочая температура",
        "source_id": TEXT,
        "quote": "Температура от 10 до 70 C",
    },
    "load_bearing": {
        "value": "cyclic",
        "inferred": True,
        "basis": "пиковый момент при работе",
        "source_id": TEXT,
        "quote": "Пиковый момент 75 Нм",
    },
}
DRAFT = {"purpose": "Шестерня привода", "requirements": REQUIREMENTS, "codes": CODES}
QUESTION = {
    "title": "В какой среде работает деталь",
    "impact": "Влияет на выбор материала",
    "options": ["вода", "масло"],
    "suggested": "вода",
    "basis": "Деталь привода насоса",
}


def script(**overrides):
    base = {"interpreter": [reply(DRAFT)], "checker": [reply({})]}
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


async def send(http, job_id: str, message: str):
    response = await http.post(
        f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": message}
    )
    assert response.status_code == 200, response.text


async def run(pg, job_id: str, model: ScriptedModel):
    """Stage one as the queue would run it: with the flags of the task waiting for it."""
    pg.stage1.runner.model = model
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id)
    waiting = [a for a in await todo(pg, "stage1") if a["job_id"] == job_id]
    flags = waiting[-1] if waiting and waiting[-1]["revision"] == job.revision else {}
    await pg.stage1.run(
        job_id,
        job.revision,
        flags.get("start", False),
        flags.get("correction", False),
        flags.get("typed"),
    )
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def revise(pg, job_id: str) -> None:
    """A correction the assistant applied: a new revision with its stage-one task."""
    async with pg.uow() as uow:
        await changed(uow, await uow.jobs.get(job_id, lock=True), "Правка", correction=True)
        await uow.commit()


async def turn(pg, job_id: str, model: ScriptedModel):
    """The assistant's answer to what the user sent, as the queue would run it."""
    pg.stage1.runner.model = model
    await pg.steering.deliver(job_id, force=True)
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def upload(http, job_id: str, name: str, content: bytes | None = None):
    content = content if content is not None else Path("tests/fixtures", name).read_bytes()
    response = await http.post(
        f"/api/v1/jobs/{job_id}/attachments",
        files={"file": (name, content)},
        data={"request_id": rid()},
    )
    assert response.status_code == 201, response.text


async def answer(http, job, answers: dict):
    response = await http.post(
        f"/api/v1/jobs/{job.id}/answers",
        json={"request_id": rid(), "expected_revision": job.revision, "answers": answers},
    )
    assert response.status_code == 200, response.text


async def rows(pg, sql: str, **params):
    async with pg.engine.connect() as connection:
        return [dict(r._mapping) for r in await connection.execute(text(sql), params)]


async def chat(http, job_id: str) -> list[dict]:
    return (await http.get(f"/api/v1/jobs/{job_id}")).json()["messages"]


def sent(model: ScriptedModel, agent: str, index: int = 0) -> str:
    """The data part of the agent's first user turn."""
    return model.requests[agent][index]["messages"][1]["content"][0]["text"]


async def test_full_run_hands_the_card_to_parameter_selection(pg, http):
    model = script()
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), model)
    card = job.card
    # The ready card waits in the queue for parameter selection.
    assert job.status == Status.QUEUED and job.stage == "parameters"
    assert card.readiness == "ready" and card.questions == []
    assert [r.key for r in card.requirements] == [
        "service_temp_max_c",
        "load_bearing",
        "torque_nominal",
        "torque_peak",
    ]
    temperature, load = card.requirements[0], card.requirements[1]
    assert (temperature.value, temperature.provenance, temperature.verified) == (
        "от 10 до 70",
        "document",
        True,
    )
    # An inferred code is an assumption: selection reads it, nobody is asked to confirm it.
    assert (load.provenance, load.mandatory, load.verified) == ("assumption", False, False)
    assert load.conditions == "пиковый момент при работе"
    attachment = next(f for f in card.files if f.kind == "txt")
    assert temperature.sources[0].source_id == f"{attachment.id}:1"
    assert temperature.sources[0].method == "text"
    assert card.geometry.units == "mm" and card.geometry.extents == [10.0, 20.0, 30.0]
    assert card.stl_analysis.report["units"]["coordinate_unit"] == "mm"
    assert card.versions["requirement_keys"] == "2"
    assert {"prompt.interpreter", "prompt.checker"} < set(card.versions)
    assert set(model.requests) == {"interpreter", "checker"}
    reading = sent(model, "interpreter")
    assert "Номинальный момент 25 Нм" in reading and "<requirement_keys>" in reading
    assert "<stl>" not in reading and "<stl_report>" not in reading
    checking = model.requests["checker"][0]["messages"][1]["content"]
    assert "<stl_report>" in checking[0]["text"] and '"codes"' in checking[0]["text"]
    # The report replaces the summary; the projections still show the shape.
    assert "<stl>" not in checking[0]["text"] and checking[-1]["type"] == "image_url"
    queued = await rows(
        pg, "SELECT task_name, args FROM procrastinate_jobs WHERE queue_name = 'stage2'"
    )
    assert queued == [
        {
            "task_name": "stage2.select_parameters",
            "args": {"job_id": job.id, "revision": job.revision},
        }
    ]
    traces = await rows(
        pg, "SELECT agent, response, cached FROM agent_calls WHERE job_id = :j", j=job.id
    )
    assert sorted(t["agent"] for t in traces) == ["checker", "interpreter"]
    assert all(t["response"] for t in traces)
    async with pg.uow() as uow:
        assert (await uow.traces.usage(job.id))[0] == 2
    events = await rows(pg, "SELECT payload FROM events WHERE job_id = :j ORDER BY seq", j=job.id)
    # Each agent's call reaches the chat as it runs, its reasoning in between.
    assert [
        (e["payload"]["type"], e["payload"]["data"]["agent"])
        for e in events
        if e["payload"]["type"].startswith("agent.")
    ] == [
        (kind, agent)
        for agent in ("interpreter", "checker")
        for kind in ("agent.started", "agent.thinking", "agent.finished")
    ]
    exported = (await http.get(f"/api/v1/jobs/{job.id}/card")).json()
    assert exported == card.model_dump(mode="json")


async def todo(pg, queue: str) -> list[dict]:
    found = await rows(
        pg, "SELECT args FROM procrastinate_jobs WHERE queue_name = :q AND status = 'todo'", q=queue
    )
    return [row["args"] for row in found]


async def finished(pg, http):
    """A job whose pipeline ran to the end; without a slicer here, no project is made."""
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), script())
    await pg.pipeline.run(job.id, job.revision)
    async with pg.uow() as uow:
        return await uow.jobs.get(job.id)


def assistant(*replies, **agents) -> ScriptedModel:
    return script(assistant=list(replies), **agents)


START = reply("Начинаю", tool_calls=[call("start_project", {"title": "Коробка"})])


async def test_a_greeting_is_answered_without_any_work(pg, http):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    await send(http, job_id, "Привет")
    assert await todo(pg, "steer") == [{"job_id": job_id}]
    job = await turn(pg, job_id, assistant(reply("Привет — пришлите модель STL.")))
    assert (job.status, job.revision, job.projects, job.card) == (Status.DRAFT, 0, [], None)
    last = (await chat(http, job_id))[-1]
    assert (last["role"], last["text"]) == ("assistant", "Привет, пришлите модель STL")
    assert await todo(pg, "stage1") == []


async def test_files_sent_with_a_message_stay_with_it_and_start_the_first_project(pg, http):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    await upload(http, job_id, "box.stl")
    await upload(http, job_id, "task.txt")
    await send(http, job_id, "Нужна такая деталь")
    message = (await chat(http, job_id))[-1]
    attachments = (await http.get(f"/api/v1/jobs/{job_id}")).json()["attachments"]
    assert set(message["attachment_ids"]) == {a["id"] for a in attachments}
    assert not any(a["draft"] for a in attachments)
    model = assistant(
        reply("", tool_calls=[call("start_project", {"title": "Коробка", "notes": "На улице"})])
    )
    job = await turn(pg, job_id, model)
    assert [(p.number, p.title, p.notes) for p in job.projects] == [(1, "Коробка", "На улице")]
    assert job.projects[0].first_message == message["seq"]
    assert await todo(pg, "stage1") == [{"job_id": job_id, "revision": 1, "start": True}]
    tools = model.requests["assistant"][0]["tools"]
    assert [t["function"]["name"] for t in tools][:2] == ["start_project", "update_project"]
    job = await run(pg, job_id, script())
    assert {f.filename for f in job.card.files} == {"box.stl", "task.txt"}
    assert job.status == Status.QUEUED
    reading = sent(job and pg.stage1.runner.model, "interpreter")
    assert "Из разговора в чате до начала проекта. На улице" in reading
    assert "Нужна такая деталь" in reading


async def test_a_start_without_a_model_is_refused_and_the_assistant_asks_for_it(pg, http):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    await upload(http, job_id, "task.txt")
    await send(http, job_id, "Вот ТЗ")
    job = await turn(pg, job_id, assistant(START, reply("Пришлите модель STL")))
    assert job.projects == [] and await todo(pg, "stage1") == []
    assert (await chat(http, job_id))[-1]["text"] == "Пришлите модель STL"


async def test_a_chat_reply_after_the_project_keeps_it(pg, http):
    """Regression: «Спасибо» after the project queued selection and slicing all over again."""
    done = await finished(pg, http)
    assert (done.status, done.stage, done.outcome) == (Status.COMPLETED, "done", "not_sliced")
    parameters = (await http.get(f"/api/v1/jobs/{done.id}/parameters")).json()
    await send(http, done.id, "Спасибо")
    job = await turn(pg, done.id, assistant(reply("Пожалуйста")))
    assert (job.status, job.stage, job.outcome) == (Status.COMPLETED, "done", "not_sliced")
    assert (job.parameters, job.result, job.card) == (done.parameters, done.result, done.card)
    assert job.revision == done.revision
    assert (await http.get(f"/api/v1/jobs/{job.id}/parameters")).json() == parameters
    assert (await chat(http, job.id))[-1]["text"] == "Пожалуйста"


async def test_a_new_part_after_the_project_starts_a_project_of_its_own(pg, http):
    """Regression: a second part redid the first project with the files of both."""
    done = await finished(pg, http)
    await upload(http, done.id, "other.stl", Path("tests/fixtures/box.stl").read_bytes())
    await send(http, done.id, "Ещё один проект, вот другая деталь")
    job = await turn(pg, done.id, assistant(START))
    assert [p.number for p in job.projects] == [1] and job.card is None
    assert (job.parameters, job.result, job.outcome, job.answers) == (None, None, None, {})
    job = await run(pg, job.id, script())
    assert {f.filename for f in job.card.files} == {"other.stl"}
    texts = [m["text"] for m in await chat(http, job.id)]
    assert texts[-3:-1] == ["Ещё один проект, вот другая деталь", "Начинаю"]


async def test_a_correction_after_the_project_continues_the_checker_dialog(pg, http):
    done = await finished(pg, http)
    await send(http, done.id, "Температура до 90 градусов")
    summary = "Температуру поменял на 90 градусов: пересчитываю материал."
    update = reply("", tool_calls=[call("update_project", {"summary": summary})])
    job = await turn(pg, done.id, assistant(update))
    message = [m for m in await chat(http, job.id) if m["role"] == "user"][-1]
    assert await todo(pg, "stage1") == [
        {"job_id": job.id, "revision": job.revision, "start": False, "correction": True}
        | {"typed": [message["id"]]}
    ]
    model = script()
    job = await run(pg, job.id, model)
    assert set(model.requests) == {"checker"} and job.status == Status.QUEUED
    follow = model.requests["checker"][0]["messages"][-1]["content"]
    assert "Правка пользователя" in follow and "Температура до 90 градусов" in follow


async def test_continue_after_a_stop_resumes_the_work(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
    retried = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    revision = retried.json()["revision"]
    assert await todo(pg, "stage1") == [{"job_id": job_id, "revision": revision, "start": True}]
    job = await run(pg, job_id, script())
    assert job.status == Status.QUEUED


UPDATE = reply("", tool_calls=[call("update_project", {"summary": "Учитываю ответ"})])


async def asked(pg, http, **overrides):
    model = script(checker=[reply({"questions": [QUESTION]})], **overrides)
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), model)
    return job, model


async def test_checker_questions_wait_for_answers_in_the_same_dialog(pg, http):
    job, first = await asked(pg, http)
    assert job.status == Status.WAITING and job.stage == "understanding"
    [question] = job.card.questions
    assert question.id.startswith("clarify.") and question.blocking
    assert await rows(pg, "SELECT id FROM procrastinate_jobs WHERE queue_name = 'stage2'") == []
    await answer(http, job, {question.id: "вода"})
    fix = {
        "code_fixes": [
            {
                "code": "chemical_resistance",
                "value": "water",
                "source_id": f"a:{question.id}",
                "quote": "вода",
            }
        ]
    }
    model = script(checker=[reply(fix)])
    job = await run(pg, job.id, model)
    # Only the checker runs again, continuing its own dialog.
    assert set(model.requests) == {"checker"}
    dialog = model.requests["checker"][0]["messages"]
    assert [m["role"] for m in dialog] == ["system", "user", "assistant", "user"]
    assert dialog[1] == first.requests["checker"][0]["messages"][1]
    assert json.loads(dialog[2]["content"])["questions"][0]["title"] == QUESTION["title"]
    assert (
        f'<source id="a:{question.id}">' in dialog[3]["content"] and "вода" in dialog[3]["content"]
    )
    assert job.status == Status.QUEUED and job.card.readiness == "ready"
    assert [(q.answer, q.blocking) for q in job.card.questions] == [("вода", False)]
    water = next(r for r in job.card.requirements if r.key == "chemical_resistance")
    assert (water.value, water.provenance, water.verified) == ("water", "user", True)
    assert water.sources[0].source_id == f"answer:{question.id}"


async def test_dont_know_lets_the_checker_assume_and_the_card_goes_on(pg, http):
    job, _ = await asked(pg, http)
    await answer(http, job, {job.card.questions[0].id: "не знаю"})
    model = script(checker=[reply({"assumptions": [{"text": "Деталь работает на воздухе"}]})])
    job = await run(pg, job.id, model)
    assert '<source id="a:' in model.requests["checker"][0]["messages"][3]["content"]
    assert job.status == Status.QUEUED and job.card.readiness == "preliminary"
    assert [(q.answer, q.blocking) for q in job.card.questions] == [("Не знаю", False)]
    assert [a.text for a in job.card.assumptions] == ["Деталь работает на воздухе"]


async def test_earlier_answers_reach_the_agents_when_the_work_runs_again(pg, http):
    """Regression: the interpreter and the checker never saw answers given before."""
    job, _ = await asked(pg, http)
    question = job.card.questions[0]
    await answer(http, job, {question.id: "морская вода"})
    job = await run(pg, job.id, script(checker=[reply({})]))
    await send(http, job.id, "Сделай деталь прочнее")
    model = script()
    await run(pg, job.id, model)
    cited = f'<source id="a:{question.id}">{QUESTION["title"]} морская вода</source>'
    assert cited in sent(model, "interpreter")
    assert cited in model.requests["checker"][0]["messages"][1]["content"][0]["text"]


async def test_a_typed_reply_counts_as_the_answer(pg, http):
    job, _ = await asked(pg, http)
    await send(http, job.id, "Работает в масле")
    await turn(pg, job.id, assistant(UPDATE))
    model = script(checker=[reply({})])
    job = await run(pg, job.id, model)
    assert set(model.requests) == {"checker"}
    follow = model.requests["checker"][0]["messages"][3]["content"]
    assert "Работает в масле" in follow and '<source id="m1">' in follow
    assert job.status == Status.QUEUED


async def test_new_files_while_questions_are_open_start_over(pg, http):
    job, _ = await asked(pg, http)
    content = Path("tests/fixtures/task.docx").read_bytes()
    await http.post(
        f"/api/v1/jobs/{job.id}/attachments",
        files={"file": ("extra.docx", content)},
        data={"request_id": rid()},
    )
    await send(http, job.id, "Добавил чертёж")
    await turn(pg, job.id, assistant(UPDATE))
    model = script()
    job = await run(pg, job.id, model)
    assert set(model.requests) == {"interpreter", "checker"}
    assert "extra.docx" in {f.filename for f in job.card.files}


async def test_newer_revision_discards_the_running_result(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")

    async def edit_meanwhile(messages):
        await revise(pg, job_id)
        return reply(DRAFT)

    job = await run(pg, job_id, script(interpreter=[edit_meanwhile]))
    assert job.status == Status.QUEUED and job.card is None


async def test_stop_takes_effect_at_the_next_safe_point(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")

    async def stop_meanwhile(messages):
        await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
        return reply(DRAFT)

    model = script(interpreter=[stop_meanwhile])
    job = await run(pg, job_id, model)
    assert job.status == Status.STOPPED and "checker" not in model.requests


async def test_provider_failure_keeps_files_and_reports_a_plain_message(pg, http):
    failure = AppError("Модель не отвечает, попробуйте позже", "model_unavailable", 503)
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), script(interpreter=[failure]))
    assert job.status == Status.FAILED and job.error == "Модель не отвечает, попробуйте позже"
    snapshot = (await http.get(f"/api/v1/jobs/{job.id}")).json()
    document = next(a for a in snapshot["attachments"] if a["kind"] == "txt")
    assert document["status"] == "completed"


async def test_broken_file_blocks_selection_but_not_interpretation(pg, http):
    job = await run(pg, await job_with(http, "box.stl", "task.txt", "corrupt.pdf"), script())
    assert job.status == Status.WAITING
    assert any("corrupt.pdf" in r for r in job.card.blocked_actions["select_parameters"])
    assert len(job.card.requirements) == 4


async def test_unexpected_error_marks_the_job_failed(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    with pytest.raises(KeyError):
        await run(pg, job_id, script(interpreter=[KeyError("bug")]))
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id)
    assert job.status == Status.FAILED and job.error.startswith("Внутренняя ошибка")


async def test_files_attached_during_a_run_leave_the_card_going_on(pg, http):
    """The files go with the next message to the assistant; the card is not held back."""
    job_id = await job_with(http, "box.stl", "task.txt")

    async def attach_meanwhile(messages):
        content = Path("tests/fixtures/task.docx").read_bytes()
        await http.post(
            f"/api/v1/jobs/{job_id}/attachments",
            files={"file": ("extra.docx", content)},
            data={"request_id": rid()},
        )
        return reply({})

    job = await run(pg, job_id, script(checker=[attach_meanwhile]))
    assert job.files_changed and job.status == Status.QUEUED and job.stage == "parameters"
    assert "Файлы изменились" not in [m["text"] for m in await chat(http, job_id)]


async def test_a_partial_stl_report_is_not_cached(pg, http, monkeypatch):
    """Regression: a report cut by the time limit was cached and reused by every retry."""
    analyze = pg.stage1.files.analyze
    calls = []

    async def cut_short(key, units, cache_key):
        calls.append(units)
        return {**await analyze(key, units, cache_key), "status": "partial"}

    monkeypatch.setattr(pg.stage1.files, "analyze", cut_short)
    job_id = await job_with(http, "box.stl", "task.txt")
    await run(pg, job_id, script())
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    await run(pg, job_id, script())
    assert calls == ["mm", "mm"]
    # Agent results and the checker's dialogs are cached, the cut report is not.
    cached = (
        "SELECT key FROM operation_cache WHERE key NOT LIKE 'agent:%' AND key NOT LIKE 'stage1:%'"
    )
    assert await rows(pg, cached) == []


async def test_a_failed_document_is_read_again_on_retry(pg, http, monkeypatch):
    """Regression: a temporary parse failure stayed until the file was uploaded again."""
    inspect = pg.stage1.files.inspect
    failures = [AppError("Страница PDF не обработана за 30 секунд", "page_timeout", 503)]

    async def flaky(key, kind):
        if failures:
            raise failures.pop()
        return await inspect(key, kind)

    monkeypatch.setattr(pg.stage1.files, "inspect", flaky)
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), script())
    assert any("task.txt" in r for r in job.card.blocked_actions["select_parameters"])
    await http.post(f"/api/v1/jobs/{job.id}/control/retry", json={"request_id": rid()})
    job = await run(pg, job.id, script())
    assert not any("task.txt" in r for r in job.card.blocked_actions.get("select_parameters", []))
    assert len(job.card.requirements) == 4


async def test_stop_interrupts_a_model_call_in_flight(pg, http, monkeypatch):
    monkeypatch.setattr("src.backend.agents.stage1.CHECK_SECONDS", 0.05)
    job_id = await job_with(http, "box.stl", "task.txt")
    cancelled = asyncio.Event()

    async def endless(messages):
        await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    job = await asyncio.wait_for(run(pg, job_id, script(interpreter=[endless])), 10)
    assert job.status == Status.STOPPED and cancelled.is_set()
    # Regression: without an event the open chat stayed on "Останавливаем" forever.
    events = await rows(
        pg, "SELECT payload FROM events WHERE job_id = :j ORDER BY seq DESC LIMIT 1", j=job_id
    )
    assert (events[0]["payload"]["type"], events[0]["payload"]["status"]) == (
        "job.stopped",
        "stopped",
    )


async def test_the_chat_view_leaves_out_the_full_stl_report(pg, http):
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), script())
    snapshot = (await http.get(f"/api/v1/jobs/{job.id}")).json()
    assert "stl_analysis" not in snapshot["job"]["card"]
    assert snapshot["job"]["card"]["geometry"]["extents"] == [10.0, 20.0, 30.0]


async def test_events_start_at_the_current_revision_and_wake_on_commit(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    await run(pg, job_id, script())
    await revise(pg, job_id)
    async with pg.uow() as uow:
        revision = (await uow.jobs.get(job_id)).revision
    stream = await pg.jobs.follow("alice", job_id, None)
    first = await anext(stream)
    assert (first.type, first.revision) == ("job.changed", revision)
    waiting = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.2)
    assert not waiting.done()
    await pg.stage1.store.event(job_id, revision, "files.started", "Читаю файлы")
    event = await asyncio.wait_for(waiting, 2)
    assert event.type == "files.started"
    await stream.aclose()


async def test_a_question_the_checker_drops_in_silence_is_asked_anyway(pg, http):
    """Regression: the checker turned questions into assumptions and nobody could see why."""
    balance = {"title": "Нужна ли балансировка", "options": ["да", "нет"]}
    finish = {"title": "Можно ли дорабатывать отверстие", "options": ["да", "нет"]}
    draft = {**DRAFT, "questions": [finish, balance]}
    review = {
        "waived": [{"id": "q1", "reason": "Допуск обеспечивает печать, так сказано в ТЗ"}],
        "assumptions": [{"text": "Доработки нет", "basis": "ТЗ"}],
    }
    model = script(interpreter=[reply(draft)], checker=[reply(review)])
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), model)
    assert [q.title for q in job.card.questions] == ["Нужна ли балансировка"]
    assert [(w.title, w.reason) for w in job.card.waived] == [
        ("Можно ли дорабатывать отверстие", "Допуск обеспечивает печать, так сказано в ТЗ")
    ]
    checker = model.requests["checker"][0]["messages"][1]["content"][0]["text"]
    assert '"id": "q1"' in checker and '"id": "q2"' in checker
    events = await rows(pg, "SELECT payload FROM events WHERE job_id = :j", j=job.id)
    done = next(e["payload"] for e in events if e["payload"]["type"] == "checking.completed")
    assert done["data"]["waived"][0]["title"] == "Можно ли дорабатывать отверстие"


async def test_the_answers_about_a_finished_part_hint_the_next_one(pg, http):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    await upload(http, job_id, "box.stl")
    await upload(http, job_id, "task.txt")
    await send(http, job_id, "Шестерня")
    await turn(pg, job_id, assistant(START))
    job = await run(pg, job_id, script(checker=[reply({"questions": [QUESTION]})]))
    await answer(http, job, {job.card.questions[0].id: "вода"})
    job = await run(pg, job_id, script(checker=[reply({})]))
    await pg.pipeline.run(job_id, job.revision)
    await upload(http, job_id, "other.stl", Path("tests/fixtures/box.stl").read_bytes())
    await send(http, job_id, "Теперь вторая деталь")
    job = await turn(pg, job_id, assistant(START))
    assert [p.number for p in job.projects] == [1, 2]
    assert job.projects[0].answers == {QUESTION["title"]: "вода"} and job.answers == {}
    model = script()
    job = await run(pg, job_id, model)
    assert {f.filename for f in job.card.files} == {"other.stl"}
    checking = model.requests["checker"][0]["messages"][1]["content"][0]["text"]
    assert f'<earlier_answers>\n[\n "{QUESTION["title"]} вода"\n]' in checking
    reading = sent(model, "interpreter")
    assert "Теперь вторая деталь" in reading and "Шестерня" not in reading


async def test_files_alone_go_to_the_assistant_and_an_empty_message_is_refused(pg, http):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    empty = await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid()})
    assert (empty.status_code, empty.json()["code"]) == (422, "empty_message")
    await upload(http, job_id, "box.stl")
    await send(http, job_id, "")
    [message] = await chat(http, job_id)
    assert message["text"] == "" and len(message["attachment_ids"]) == 1
    model = assistant(START)
    job = await turn(pg, job_id, model)
    assert [p.number for p in job.projects] == [1]
    assert "[вложения box.stl]" in model.requests["assistant"][0]["messages"][-1]["content"]
