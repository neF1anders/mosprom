import json
from uuid import uuid4

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.models import Conflict, Geometry, Question, TaskCard
from src.backend.worker import execute

pytestmark = pytest.mark.integration


class ModelDouble:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = 0
        self.callback = None

    async def complete(self, messages, tools):
        self.calls += 1
        if self.callback:
            callback, self.callback = self.callback, None
            await callback()
        if self.mode == "failure":
            raise AppError("temporary failure", "model_unavailable", 503)
        if self.mode == "invalid":
            return {"content": "bad json"}
        if self.mode in {"tool", "unknown", "arguments", "repeat"} and (
            self.calls == 1 or self.mode == "repeat"
        ):
            name = "search_knowledge" if self.mode != "unknown" else "run_shell"
            args = "broken" if self.mode == "arguments" else json.dumps({"query": "плотность"})
            return {
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": name, "arguments": args}}
                ]
            }
        context = json.loads(messages[1]["content"])
        sources = context["sources"]
        key = next(iter(sources))
        source = sources[key]
        card = TaskCard(
            purpose="Шестерня",
            requirements=[
                {
                    "key": "назначение",
                    "value": source["text"],
                    "sources": [{"source_id": key, "quote": source["text"]}],
                }
            ],
        )
        if self.mode == "question":
            card.questions = [Question(id="load", title="Какая нагрузка?", reason="Для параметров")]
        if self.mode == "conflict":
            card.conflicts = [Conflict(id="size", title="Размер", options=["80", "100"])]
        return {
            "content": card.model_dump_json(exclude={"stl_analysis", "answers", "resolutions"}),
            "usage": {"prompt_tokens": 100},
        }


class GeometryDouble:
    async def analyze(self, attachment, units):
        return (
            Geometry(readable=True, units=units, extents=[10, 20, 30]),
            {"file": {"sha256": attachment.sha256}, "units": {"input_unit": units}},
            False,
        )


async def run_work(pg):
    async with pg.uow() as uow:
        work = await uow.queue.claim(str(uuid4()))
        await uow.commit()
    assert work is not None
    await execute(pg, work)
    return (await pg.jobs.snapshot(work.job_id))["job"]


@pytest.mark.parametrize(
    "mode",
    ["ok", "question", "conflict", "tool", "unknown", "arguments", "repeat", "invalid", "failure"],
)
async def test_T07_T09_T10_pipeline_outcomes(pg, mode):
    pg.pipeline.extraction.model = ModelDouble(mode)
    created = await pg.jobs.create(str(uuid4()), "Flow")
    await pg.messages.send(created["id"], str(uuid4()), "Шестерня 25 Нм")
    result = await run_work(pg)
    expected = "failed" if mode in {"repeat", "invalid", "failure"} else "waiting_user"
    assert result["status"] == expected
    events = await pg.jobs.events(created["id"])
    assert events
    if mode == "tool":
        assert any(e.type == "tool.completed" for e in events)


@pytest.mark.parametrize("action", ["stop", "edit", "status", "retry", "resume"])
async def test_T11_safe_point_interruption(pg, action):
    model = ModelDouble()
    pg.pipeline.extraction.model = model
    created = await pg.jobs.create(str(uuid4()), "Safe point")
    await pg.messages.send(created["id"], str(uuid4()), "Шестерня 25 Нм")

    async def callback():
        if action == "edit":
            await pg.messages.send(created["id"], str(uuid4()), "Теперь 30 Нм")
        elif action == "status":
            await pg.messages.send(created["id"], str(uuid4()), "статус")
        else:
            await pg.control.run(created["id"], str(uuid4()), action)

    model.callback = callback
    result = await run_work(pg)
    if action == "stop":
        assert result["status"] == "stopped"
    elif action == "status":
        assert result["status"] == "waiting_user"
    else:
        assert result["status"] == "queued"
        assert result["card"] is None


@pytest.mark.parametrize("answer", ["mm", "cm", "inch", "m", "Не знаю"])
async def test_T07_answers_recompute_and_unknown_is_not_fact(pg, answer):
    model = ModelDouble()
    pg.pipeline.extraction.model = model
    created = await pg.jobs.create(str(uuid4()), "Answers")
    await pg.messages.send(created["id"], str(uuid4()), "Шестерня 25 Нм")
    job = await run_work(pg)
    result = await pg.answers.answer(
        created["id"], str(uuid4()), job["revision"], {"geometry.units": answer}
    )
    assert result["units"] == ("unknown" if answer == "Не знаю" else answer)
    job = await run_work(pg)
    assert job["card"]["readiness"] == "blocked"  # no STL even when units known


async def test_T13_ready_card_without_connected_handoff(pg):
    from src.backend.domain.models import DOCUMENT_VERSION, Attachment

    pg.pipeline.extraction.model = ModelDouble()
    pg.pipeline.geometry = GeometryDouble()
    created = await pg.jobs.create(str(uuid4()), "Ready")
    async with pg.uow() as uow:
        job = await uow.jobs.get(created["id"], lock=True)
        a = Attachment(
            job_id=job.id,
            filename="box.stl",
            kind="stl",
            sha256="a" * 64,
            size=1,
            status="completed",
            parser_version=DOCUMENT_VERSION,
        )
        job.units = "mm"
        job.active_stl = a.id
        await uow.jobs.attachment(a)
        await uow.jobs.save(job)
        await uow.commit()
    await pg.messages.send(created["id"], str(uuid4()), "Шестерня")
    result = await run_work(pg)
    assert result["status"] == "completed"
    assert result["handoff"] == "not_connected"


@pytest.mark.parametrize(
    "filename,content",
    [
        ("task.txt", b"Part requirements"),
        ("spoof.pdf", b"not pdf"),
        ("task.md", b"# Gear"),
        ("bad.docx", b"broken"),
        ("model.stl", b"broken stl"),
    ],
)
async def test_T01_preparation_keeps_other_work(pg, filename, content):
    pg.pipeline.extraction.model = ModelDouble()
    created = await pg.jobs.create(str(uuid4()), "Uploads")

    async def chunks():
        yield content

    attachment = await pg.uploads.upload(created["id"], str(uuid4()), filename, chunks())
    result = await run_work(pg)
    state = await pg.jobs.snapshot(created["id"])
    expected = "completed" if filename.endswith((".txt", ".md")) else "failed"
    assert state["attachments"][0]["status"] == expected
    assert result["status"] == "waiting_user"
    assert await pg.artifacts.read(created["id"], attachment["id"]) == content


async def test_T05_model_failure_keeps_geometry_downloadable(pg):
    from pathlib import Path

    pg.pipeline.extraction.model = ModelDouble("failure")
    created = await pg.jobs.create(str(uuid4()), "Partial geometry")

    async def chunks():
        yield Path("tests/fixtures/box.stl").read_bytes()

    await pg.uploads.upload(created["id"], str(uuid4()), "box.stl", chunks())
    await pg.messages.send(created["id"], str(uuid4()), "Корпус")
    result = await run_work(pg)
    if result["status"] == "queued":
        result = await run_work(pg)
    assert result["status"] == "failed" and result["card"] is None
    state = await pg.jobs.snapshot(created["id"])
    reports = [
        artifact for artifact in state["attachments"][0]["artifacts"] if artifact.endswith(".json")
    ]
    assert reports, "Geometry must remain owned and downloadable without an LLM card"
    report = json.loads(await pg.artifacts.read(created["id"], reports[-1]))
    assert report["geometry"]["extents"] == [10, 20, 30]
