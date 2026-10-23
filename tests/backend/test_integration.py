import asyncio
from uuid import uuid4

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.models import Event, Job, Knowledge, Status

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("copies", [1, 2, 3, 4, 5])
async def test_A02_T12_idempotent_concurrent_create(pg, copies):
    request_id = str(uuid4())
    results = await asyncio.gather(*(pg.jobs.create(request_id, "Example") for _ in range(copies)))
    assert len({r["id"] for r in results}) == 1
    assert len(await pg.jobs.list()) == 1


@pytest.mark.parametrize(
    "stage", ["before_save", "after_save", "after_event", "after_receipt", "after_enqueue"]
)
async def test_A02_transaction_rolls_back(pg, stage):
    job = Job()
    with pytest.raises(RuntimeError):
        async with pg.uow() as uow:
            if stage == "before_save":
                raise RuntimeError()
            await uow.jobs.save(job)
            if stage == "after_save":
                raise RuntimeError()
            await uow.events.append(
                Event(job_id=job.id, revision=0, type="test", status="draft", message="test")
            )
            if stage == "after_event":
                raise RuntimeError(stage)
            await uow.jobs.remember("rollback-test", "hash", {"job": job.id})
            if stage == "after_receipt":
                raise RuntimeError(stage)
            await uow.queue.enqueue(job)
            raise RuntimeError(stage)
    assert not await pg.jobs.list()
    async with pg.uow() as uow:
        assert not await uow.events.list(job.id)
        assert await uow.jobs.receipt("rollback-test", "hash") is None
        assert await uow.queue.claim("check") is None


@pytest.mark.parametrize("workers", [1, 2, 3, 4, 5])
async def test_T12_queue_single_claim(pg, workers):
    created = await pg.jobs.create(str(uuid4()), "Queue")
    await pg.messages.send(created["id"], str(uuid4()), "Шестерня")

    async def claim():
        async with pg.uow() as uow:
            work = await uow.queue.claim(str(uuid4()))
            await uow.commit()
            return work

    results = await asyncio.gather(*(claim() for _ in range(workers)))
    assert sum(r is not None for r in results) == 1


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.QUEUED, Status.RUNNING, Status.WAITING, Status.COMPLETED]
)
async def test_T11_stop_prevents_next_operation(pg, status):
    job = Job(status=status)
    async with pg.uow() as uow:
        await uow.jobs.save(job)
        await uow.commit()
    result = await pg.control.run(job.id, str(uuid4()), "stop")
    assert result["status"] == ("stopping" if status == Status.RUNNING else "stopped")


@pytest.mark.parametrize("answer", ["mm", "cm", "inch", "Не знаю", "m"])
async def test_T07_T08_stale_answers_rejected(pg, answer):
    job = await pg.jobs.create(str(uuid4()), "Test")
    with pytest.raises(AppError) as error:
        await pg.answers.answer(job["id"], str(uuid4()), 100, {"geometry.units": answer})
    assert error.value.status == 409


@pytest.mark.parametrize("count", [1, 2, 5, 20, 101])
async def test_events_cursor_no_duplicates(pg, count):
    job = await pg.jobs.create(str(uuid4()), "Events")
    async with pg.uow() as uow:
        for i in range(count):
            await uow.events.append(
                Event(job_id=job["id"], revision=0, type="test", status="completed", message=str(i))
            )
        await uow.commit()
    first = await pg.jobs.events(job["id"])
    second = await pg.jobs.events(job["id"], first[-1].event_id)
    assert not {e.event_id for e in first}.intersection(e.event_id for e in second)
    assert len(first) + len(second) == count + 1


async def test_T06_exact_knowledge_not_family_substitution(pg):
    async with pg.uow() as uow:
        await uow.knowledge.put(
            Knowledge(
                id="pla",
                material_id="proto_pla",
                aliases=["Proto PLA"],
                property="density",
                value="1.25",
                unit="g/cm3",
                text="Proto PLA плотность",
                source="fixture",
                scope="grade",
            )
        )
        await uow.commit()
    assert (await pg.knowledge.search("", "Proto PLA", "density"))["status"] == "found"
    assert (await pg.knowledge.search("", "Unknown PLA", "density"))["status"] == "not_found"


async def test_http_message_and_snapshot(http):
    job = (await http.post("/api/v1/jobs", json={"request_id": str(uuid4())})).json()
    response = await http.post(
        f"/api/v1/jobs/{job['id']}/messages",
        json={"request_id": str(uuid4()), "text": "Шестерня, 25 Нм"},
    )
    assert response.status_code == 200
    state = (await http.get(f"/api/v1/jobs/{job['id']}")).json()
    assert state["job"]["revision"] == 1
    assert state["messages"][0]["text"] == "Шестерня, 25 Нм"


@pytest.mark.parametrize(
    "name", ["../../part.txt", "..\\part.txt", "нормальный.txt", "part.txt", "part.md"]
)
async def test_T01_replayed_upload_keeps_one_attachment_and_safe_storage(pg, name):
    created = await pg.jobs.create(str(uuid4()), "Files")
    request_id = str(uuid4())

    async def chunks():
        yield "Требование 25 Нм".encode()

    first = await pg.uploads.upload(created["id"], request_id, name, chunks())
    replay = await pg.uploads.upload(created["id"], request_id, name, chunks())
    assert first["id"] == replay["id"]
    snapshot = await pg.jobs.snapshot(created["id"])
    assert len(snapshot["attachments"]) == 1
    assert "/" not in first["filename"] and "\\" not in first["filename"]
    assert len(list(pg.files.root.iterdir())) == 1
