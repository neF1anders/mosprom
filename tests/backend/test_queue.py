"""Messages queued while the job works and their delivery at its safe points, on PostgreSQL.

Only the provider is scripted; the agent «Корректировка» answers as the agent ``steer``.
"""

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from src.backend.agents.stage1 import CORRECTION, correction_key
from src.backend.domain.errors import AppError
from src.backend.domain.model_settings import ModelSettings
from src.backend.domain.models import Status, now
from src.backend.infrastructure.qwen import QwenClient
from src.backend.pipeline.parameters import ParameterPipeline, PipelineSettings
from src.backend.services.steering import CLAIM_TIMEOUT, FILES_CHANGED
from tests import model_server

from .fakes import call, reply
from .test_pipeline import CATALOG, Steps, ready_job
from .test_stage1 import QUESTION, answer, chat, job_with, rid, rows, run, script, send, sent, todo

pytestmark = pytest.mark.integration
SUMMARY = "Температуру поменял с 70 на 90 °C: пересчитываю то, что от неё зависит."
APPLIED = "Температуру поменял с 70 на 90 °C, пересчитываю то, что от неё зависит"
APPLY = reply("", tool_calls=[call("apply_correction", {"summary": SUMMARY})])
OFFTOPIC = reply("Погоду не знаю — продолжаю работу.")
TEMPERATURE = "Температура до 90 C"
FIX = {
    "code_fixes": [
        {
            "code": "service_temp_max_c",
            "value": "до 90",
            "unit": "C",
            "source_id": "m1",
            "quote": TEMPERATURE,
            "inferred": False,
        }
    ]
}
LATER = timedelta(seconds=1)


async def enqueue(http, job_id: str, text: str) -> dict:
    response = await http.post(
        f"/api/v1/jobs/{job_id}/queue", json={"request_id": rid(), "text": text}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def act(http, job_id: str, item_id: str, action: str, **body):
    path = f"/api/v1/jobs/{job_id}/queue/{item_id}/{action}"
    return await http.post(path, json={"request_id": rid(), **body})


def queued_while(http, job_id: str, text: str, review: dict | None = None):
    """A checker reply that queues a message while stage one still runs."""

    async def meanwhile(messages):
        await enqueue(http, job_id, text)
        return reply(review or {})

    return meanwhile


async def waiting(pg, job_id: str):
    async with pg.uow() as uow:
        return await uow.queued.list(job_id)


async def hold(pg, job_id: str, **changes) -> None:
    """Puts the job's queued messages in the state a delivery leaves them in."""
    async with pg.uow() as uow:
        for message in await uow.queued.list(job_id):
            await uow.queued.save(message.model_copy(update=changes))
        await uow.commit()


async def current(pg, job_id: str):
    async with pg.uow() as uow:
        return await uow.jobs.get(job_id)


async def run_queued(pg, model):
    """Runs the stage-one task the job waits for, with the flags it was queued with."""
    [task] = await todo(pg, "stage1")
    pg.stage1.runner.model = model
    await pg.stage1.run(**task)
    return await current(pg, task["job_id"])


async def events(pg, job_id: str) -> list[dict]:
    found = await rows(pg, "SELECT payload FROM events WHERE job_id = :j ORDER BY seq", j=job_id)
    return [row["payload"] for row in found]


async def kinds(http, job_id: str) -> list[tuple[str, str, str]]:
    return [(m["role"], m["kind"], m["text"]) for m in await chat(http, job_id)]


def stage_two(pg, steps: Steps, check=None, check_gcode=None) -> ParameterPipeline:
    """Stand-in steps; the messages queued meanwhile are delivered between them."""
    return ParameterPipeline(
        pg.uow,
        CATALOG,
        steps.select,
        check or steps.check,
        steps,
        check_gcode or steps.check_gcode,
        PipelineSettings(5),
        safe_point=pg.steering.deliver,
    )


def correction(job_id: str, revision: int) -> dict:
    return {"job_id": job_id, "revision": revision, "start": False, "correction": True}


async def test_a_message_waits_while_the_job_works_and_goes_at_once_otherwise(pg, http, other):
    job_id = (await http.post("/api/v1/jobs", json={"request_id": rid()})).json()["id"]
    sent_now = await enqueue(http, job_id, "Шестерня привода")
    assert (sent_now["job"]["revision"], sent_now["job"]["status"]) == (1, "queued")
    assert sent_now["job"]["title"] == "Шестерня привода" and sent_now["queued"] == []
    queued = await enqueue(http, job_id, TEMPERATURE)
    assert queued["job"]["revision"] == 1
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert [m["text"] for m in snapshot["messages"]] == ["Шестерня привода"]
    [message] = snapshot["queued"]
    assert (message["text"], message["status"], message["attempts"]) == (TEMPERATURE, "queued", 0)
    assert "claim" not in message and queued["queued"] == [message]
    assert "queue.added" in [e["type"] for e in await events(pg, job_id)]
    assert [task["revision"] for task in await todo(pg, "stage1")] == [1]
    for number in range(9):
        await enqueue(http, job_id, f"Ещё {number}")
    full = await http.post(f"/api/v1/jobs/{job_id}/queue", json={"request_id": rid(), "text": "x"})
    assert (full.status_code, full.json()["code"]) == (409, "queue_full")
    stranger = await other.post(
        f"/api/v1/jobs/{job_id}/queue", json={"request_id": rid(), "text": "x"}
    )
    assert stranger.status_code == 404


async def test_only_a_waiting_message_is_edited_deleted_or_sent(pg, http):
    job_id = await job_with(http, "box.stl")
    [first] = (await enqueue(http, job_id, TEMPERATURE))["queued"]
    await hold(pg, job_id, attempts=2)
    body = {"request_id": rid(), "text": "Температура до 80 C"}
    path = f"/api/v1/jobs/{job_id}/queue/{first['id']}/edit"
    edited = await http.post(path, json=body)
    [after] = edited.json()["queued"]
    # A new text gets new attempts.
    assert (after["text"], after["attempts"]) == ("Температура до 80 C", 0)
    assert (await http.post(path, json=body)).json() == edited.json()
    conflict = await http.post(path, json={**body, "text": "Другое"})
    assert (conflict.status_code, conflict.json()["code"]) == (409, "idempotency_conflict")
    await hold(pg, job_id, status="delivering", claim="c", claimed_at=now())
    for action, extra in [("edit", {"text": "x"}), ("delete", {}), ("send", {})]:
        response = await act(http, job_id, first["id"], action, **extra)
        assert (response.status_code, response.json()["code"]) == (409, "queued_busy")
    # A claim that outlived its delivery no longer holds the message.
    await hold(pg, job_id, claimed_at=now() - CLAIM_TIMEOUT - LATER)
    deleted = await act(http, job_id, first["id"], "delete")
    assert deleted.status_code == 200 and deleted.json()["queued"] == []
    for action, extra in [("edit", {"text": "x"}), ("delete", {}), ("send", {})]:
        response = await act(http, job_id, first["id"], action, **extra)
        assert (response.status_code, response.json()["code"]) == (409, "queued_gone")


async def test_an_offtopic_message_at_the_end_of_stage_one_leaves_the_work_alone(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    model = script(checker=[queued_while(http, job_id, "Какая сегодня погода")], steer=[OFFTOPIC])
    job = await run(pg, job_id, model)
    assert (job.revision, job.status, job.stage, job.card.revision) == (
        1,
        Status.QUEUED,
        "parameters",
        1,
    )
    assert await todo(pg, "stage2") == [{"job_id": job_id, "revision": 1}]
    assert (await kinds(http, job_id))[-2:] == [
        ("user", "offtopic", "Какая сегодня погода"),
        ("assistant", "steer", "Погоду не знаю, продолжаю работу"),
    ]
    assert await waiting(pg, job_id) == []
    assert (await events(pg, job_id))[-1]["type"] == "steer.replied"
    state = model.requests["steer"][0]["messages"][1]["content"]
    assert '"этап": "подбор параметров"' in state and '"назначение": "Шестерня привода"' in state
    assert state.endswith("<messages>\nКакая сегодня погода\n</messages>")
    # The agents that make the card never read it.
    await send(http, job_id, "Момент 30 Нм")
    model = script()
    await run(pg, job_id, model)
    assert "Какая сегодня погода" not in sent(model, "interpreter")


async def test_a_correction_at_the_end_of_stage_one_is_one_more_turn_of_the_checker(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    first = script(checker=[queued_while(http, job_id, TEMPERATURE)], steer=[APPLY])
    job = await run(pg, job_id, first)
    # The new revision took the card's place in the queue of stage two.
    assert (job.revision, job.status, job.stage, job.card.revision) == (
        2,
        Status.QUEUED,
        "understanding",
        1,
    )
    assert await todo(pg, "stage2") == [] and await todo(pg, "stage1") == [correction(job_id, 2)]
    last = (await chat(http, job_id))[-1]
    assert (last["kind"], last["revision"], last["text"]) == ("chat", 2, TEMPERATURE)
    applied = (await events(pg, job_id))[-1]
    assert (applied["type"], applied["revision"], applied["data"]) == (
        "steer.applied",
        2,
        {"summary": APPLIED},
    )

    second = script(checker=[reply(FIX)])
    job = await run_queued(pg, second)
    assert set(second.requests) == {"checker"}
    dialog = second.requests["checker"][0]["messages"]
    assert [m["role"] for m in dialog] == ["system", "user", "assistant", "user"]
    assert dialog[1] == first.requests["checker"][0]["messages"][1]
    assert dialog[3]["content"].startswith(CORRECTION)
    assert f'<source id="m1">{TEMPERATURE}</source>' in dialog[3]["content"]
    assert (job.revision, job.status, job.card.revision) == (2, Status.QUEUED, 2)
    temperature = next(r for r in job.card.requirements if r.key == "service_temp_max_c")
    assert (temperature.value, temperature.provenance) == ("до 90", "user")
    started = [e["message"] for e in await events(pg, job_id) if e["type"] == "checking.started"]
    assert started[-1] == "Учитываю правку"
    assert await todo(pg, "stage2") == [{"job_id": job_id, "revision": 2}]

    # A later correction goes on in the same dialog.
    await enqueue(http, job_id, "Количество 3")
    pg.stage1.runner.model = script(steer=[APPLY])
    assert await pg.steering.deliver(job_id, 2)
    third = script(checker=[reply({})])
    await run_queued(pg, third)
    dialog = third.requests["checker"][0]["messages"]
    assert [m["role"] for m in dialog] == ["system", *["user", "assistant"] * 2, "user"]
    assert dialog[3] == second.requests["checker"][0]["messages"][3]
    assert json.loads(dialog[4]["content"])["code_fixes"][0]["value"] == "до 90"
    assert '<source id="m2">Количество 3</source>' in dialog[5]["content"]
    assert '<source id="m1">' not in dialog[5]["content"]


async def test_a_correction_before_the_first_card_reads_the_task_without_the_gate(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    await enqueue(http, job_id, TEMPERATURE)
    pg.stage1.runner.model = script(steer=[APPLY])
    assert await pg.steering.deliver(job_id, force=True)
    model = script()
    job = await run_queued(pg, model)
    assert set(model.requests) == {"interpreter", "checker"}
    assert TEMPERATURE in sent(model, "interpreter") and job.status == Status.QUEUED


async def test_new_files_make_a_correction_without_asking_the_agent(pg, http):
    job_id = await job_with(http, "box.stl", "task.txt")
    await run(pg, job_id, script())
    await enqueue(http, job_id, "Добавил чертёж")
    response = await http.post(
        f"/api/v1/jobs/{job_id}/attachments",
        files={"file": ("extra.docx", Path("tests/fixtures/task.docx").read_bytes())},
        data={"request_id": rid()},
    )
    assert response.status_code == 201, response.text
    model = script()
    pg.stage1.runner.model = model
    assert await pg.steering.deliver(job_id, 1)
    assert (await events(pg, job_id))[-1]["data"] == {"summary": FILES_CHANGED}
    job = await run_queued(pg, model)
    # The card of the old files has no dialog to go on with, and the gate is not asked.
    assert set(model.requests) == {"interpreter", "checker"}
    assert "extra.docx" in {f.filename for f in job.card.files}


async def test_a_correction_before_slicing_spares_the_slicer(pg, http):
    job_id = await ready_job(http, pg)
    steps = Steps()
    loop = asyncio.get_running_loop()

    def check_meanwhile(parameter_set):
        asyncio.run_coroutine_threadsafe(enqueue(http, job_id, TEMPERATURE), loop).result()
        return steps.check(parameter_set)

    pg.stage1.runner.model = script(steer=[APPLY])
    await stage_two(pg, steps, check=check_meanwhile).run(job_id, 1)
    assert steps.checked == [1] and steps.sliced == []
    job = await current(pg, job_id)
    assert (job.revision, job.status) == (2, Status.QUEUED)
    assert await todo(pg, "stage1") == [correction(job_id, 2)]


@pytest.mark.parametrize(
    ("decision", "revision", "status", "last"),
    [
        (OFFTOPIC, 1, Status.COMPLETED, ("assistant", "steer", "Погоду не знаю, продолжаю работу")),
        (APPLY, 2, Status.QUEUED, ("user", "chat", "Какая погода")),
    ],
)
async def test_a_message_at_the_end_of_the_work_keeps_the_project(
    pg, http, decision, revision, status, last
):
    job_id = await ready_job(http, pg)
    steps = Steps()
    loop = asyncio.get_running_loop()

    def gcode_meanwhile(key, parameter_set, iteration):
        asyncio.run_coroutine_threadsafe(enqueue(http, job_id, "Какая погода"), loop).result()
        return steps.check_gcode(key, parameter_set, iteration)

    pg.stage1.runner.model = script(steer=[decision])
    await stage_two(pg, steps, check_gcode=gcode_meanwhile).run(job_id, 1)
    job = await current(pg, job_id)
    assert (job.revision, job.status) == (revision, status)
    assert (job.stage, job.outcome, job.result.sliced) == ("done", "ready", True)
    assert (await kinds(http, job_id))[-1] == last
    corrections = [task for task in await todo(pg, "stage1") if task.get("correction")]
    assert corrections == [correction(job_id, revision)] * (revision - 1)


async def test_a_failing_agent_leaves_the_messages_queued_and_the_work_goes_on(pg, http):
    job_id = await ready_job(http, pg)
    await enqueue(http, job_id, TEMPERATURE)
    failure = AppError("Модель не отвечает, попробуйте позже", "model_unavailable", 503)
    model = script(steer=[failure])
    pg.stage1.runner.model = model
    steps = Steps()
    await stage_two(pg, steps).run(job_id, 1)
    assert (await current(pg, job_id)).status == Status.COMPLETED and steps.gcode
    # Two safe points tried, the later ones left the message for the user.
    assert len(model.requests["steer"]) == 2
    [message] = await waiting(pg, job_id)
    assert (message.status, message.claim, message.attempts) == ("queued", None, 2)
    failed = [e for e in await events(pg, job_id) if e["type"] == "steer.failed"]
    assert [e["data"] for e in failed] == [{"code": "model_unavailable"}] * 2
    # The user's own send still delivers it.
    pg.stage1.runner.model = script(steer=[OFFTOPIC])
    assert not await pg.steering.deliver(job_id, force=True)
    assert await waiting(pg, job_id) == [] and (await kinds(http, job_id))[-1][1] == "steer"


async def test_a_slow_agent_counts_as_a_failed_delivery(pg, http, monkeypatch):
    monkeypatch.setattr("src.backend.services.steering.DECIDE_SECONDS", 0.1)
    job_id = await job_with(http, "box.stl")
    await enqueue(http, job_id, TEMPERATURE)

    async def slow(messages):
        await asyncio.sleep(5)
        return OFFTOPIC

    pg.stage1.runner.model = script(steer=[slow])
    assert not await pg.steering.deliver(job_id, force=True)
    [message] = await waiting(pg, job_id)
    assert (message.status, message.attempts) == ("queued", 1)
    last = (await events(pg, job_id))[-1]
    assert (last["type"], last["data"]) == ("steer.failed", {"code": "steer_timeout"})


async def test_a_stop_during_the_decision_releases_the_messages(pg, http, monkeypatch):
    monkeypatch.setattr("src.backend.agents.stage1.CHECK_SECONDS", 0.05)
    job_id = await job_with(http, "box.stl", "task.txt")
    cancelled = asyncio.Event()

    async def stop_meanwhile(messages):
        await http.post(f"/api/v1/jobs/{job_id}/control/stop", json={"request_id": rid()})
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    model = script(checker=[queued_while(http, job_id, TEMPERATURE)], steer=[stop_meanwhile])
    job = await asyncio.wait_for(run(pg, job_id, model), 10)
    assert cancelled.is_set() and (job.revision, job.status) == (1, Status.STOPPED)
    [message] = await waiting(pg, job_id)
    assert (message.status, message.claim, message.attempts) == ("queued", None, 0)
    types = [e["type"] for e in await events(pg, job_id)]
    assert "steer.failed" not in types and types.count("job.changed") == 1


@pytest.mark.parametrize(
    ("command", "body", "typed"),
    [("messages", {"text": "Количество 3"}, ["Количество 3"]), ("control/retry", {}, [])],
)
async def test_a_send_during_the_decision_takes_the_queue_first(pg, http, command, body, typed):
    job_id = await job_with(http, "box.stl")
    await enqueue(http, job_id, TEMPERATURE)

    async def send_meanwhile(messages):
        response = await http.post(
            f"/api/v1/jobs/{job_id}/{command}", json={"request_id": rid(), **body}
        )
        assert response.status_code == 200, response.text
        return APPLY

    pg.stage1.runner.model = script(steer=[send_meanwhile])
    # The late decision is dropped: the send took the message into its revision.
    assert not await pg.steering.deliver(job_id, force=True)
    assert (await current(pg, job_id)).revision == 2
    assert [(m["revision"], m["text"]) for m in await chat(http, job_id)] == [
        (2, text) for text in [TEMPERATURE, *typed]
    ]
    assert await waiting(pg, job_id) == []
    assert await todo(pg, "stage1") == [{"job_id": job_id, "revision": 2, "start": False}]
    assert "steer.applied" not in [e["type"] for e in await events(pg, job_id)]


async def test_a_claim_left_by_a_dead_delivery_is_taken_again(pg, http):
    job_id = await job_with(http, "box.stl")
    await enqueue(http, job_id, "Какая погода")
    await hold(pg, job_id, status="delivering", claim="dead", claimed_at=now() - LATER * 30)
    model = script(steer=[OFFTOPIC])
    pg.stage1.runner.model = model
    assert not await pg.steering.deliver(job_id, 1)
    assert "steer" not in model.requests and len(await waiting(pg, job_id)) == 1
    await hold(pg, job_id, claimed_at=now() - CLAIM_TIMEOUT - LATER)
    assert not await pg.steering.deliver(job_id, 1)
    assert await waiting(pg, job_id) == [] and (await kinds(http, job_id))[-1][1] == "steer"


async def waiting_for_answers(pg, http, text: str):
    """A job whose checker asked, with a message queued while it did."""
    job_id = await job_with(http, "box.stl", "task.txt")
    review = {"questions": [QUESTION]}
    model = script(checker=[queued_while(http, job_id, text, review)])
    job = await run(pg, job_id, model)
    assert job.status == Status.WAITING and "steer" not in model.requests
    return job


async def test_while_questions_wait_the_queue_waits_and_goes_with_the_answers(pg, http):
    job = await waiting_for_answers(pg, http, "Работает в масле")
    [message] = await waiting(pg, job.id)
    assert (message.status, message.attempts) == ("queued", 0)
    question = job.card.questions[0]
    await answer(http, job, {question.id: "вода"})
    assert (await kinds(http, job.id))[-2:] == [
        ("user", "chat", "Работает в масле"),
        ("user", "answers", f"{QUESTION['title']}, вода"),
    ]
    model = script(checker=[reply({})])
    await run(pg, job.id, model)
    follow = model.requests["checker"][0]["messages"][3]["content"]
    assert '<source id="m1">Работает в масле</source>' in follow
    assert f'<source id="a:{question.id}">' in follow


async def test_send_now_on_an_idle_job_takes_the_queue_into_a_new_revision(pg, http):
    job = await waiting_for_answers(pg, http, "Работает в масле")
    [message] = await waiting(pg, job.id)
    response = await act(http, job.id, message.id, "send")
    assert response.json()["job"]["revision"] == 2 and response.json()["queued"] == []
    assert (await kinds(http, job.id))[-1] == ("user", "chat", "Работает в масле")
    assert await todo(pg, "stage1") == [{"job_id": job.id, "revision": 2, "start": False}]
    assert await rows(pg, "SELECT id FROM procrastinate_jobs WHERE queue_name = 'steer'") == []


async def test_a_second_send_now_finds_nothing_to_claim(pg, http):
    job_id = await job_with(http, "box.stl")
    [message] = (await enqueue(http, job_id, "Какая погода"))["queued"]
    for _ in range(2):
        assert (await act(http, job_id, message["id"], "send")).status_code == 200
    tasks = await rows(
        pg,
        "SELECT task_name, lock, args FROM procrastinate_jobs WHERE queue_name = 'steer'",
    )
    assert (
        tasks
        == [{"task_name": "steer.deliver", "lock": f"steer:{job_id}", "args": {"job_id": job_id}}]
        * 2
    )
    deciding, decided = asyncio.Event(), asyncio.Event()

    async def slow(messages):
        deciding.set()
        await decided.wait()
        return OFFTOPIC

    model = script(steer=[slow])
    pg.stage1.runner.model = model
    first = asyncio.ensure_future(pg.steering.deliver(job_id, force=True))
    await deciding.wait()
    assert not await pg.steering.deliver(job_id, force=True)
    decided.set()
    await first
    assert len(model.requests["steer"]) == 1
    assert [kind for _, kind, _ in await kinds(http, job_id)] == ["offtopic", "steer"]


async def test_after_the_answers_an_ordinary_message_still_goes_to_the_gate(pg, http):
    model = script(checker=[reply({"questions": [QUESTION]})])
    job = await run(pg, await job_with(http, "box.stl", "task.txt"), model)
    await answer(http, job, {job.card.questions[0].id: "вода"})
    job = await run(pg, job.id, script(checker=[reply({})]))
    async with pg.uow() as uow:
        assert await uow.cache.get(correction_key(job.id, job.revision)) is not None
    await send(http, job.id, "Сделай деталь прочнее")
    model = script()
    await run(pg, job.id, model)
    assert "gate" in model.requests


async def test_the_model_server_drives_the_agent_through_the_real_client(pg, http):
    transport = httpx.ASGITransport(app=model_server.app)
    settings = ModelSettings("http://model/v1", "test", "test")
    client = QwenClient(lambda: settings, transport=transport)
    pg.stage1.runner.model = client
    job = await current(pg, await job_with(http, "box.stl"))
    try:
        answered = await pg.steering.steer.decide(job, ["Какая погода"])
        applied = await pg.steering.steer.decide(job, ["TEST_STEER_APPLY Температура до 90 C"])
    finally:
        await client.close()
    assert (answered.correction, answered.text) == (False, model_server.STEER_REPLY)
    assert (applied.correction, applied.text) == (True, model_server.STEER_SUMMARY)
