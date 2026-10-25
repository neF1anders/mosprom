"""HTTP commands against SQLite: atomic revisions, queueing, ownership, idempotency."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.backend.domain.models import Status
from src.backend.infrastructure.queue import TaskRunner
from src.backend.services.commands import changed

from .conftest import decoded

pytestmark = pytest.mark.integration


def rid() -> str:
    return str(uuid.uuid4())


async def new_job(http) -> str:
    response = await http.post("/api/v1/jobs", json={"request_id": rid()})
    assert response.status_code == 201
    return response.json()["id"]


async def queued(pg, job_id: str) -> list[dict]:
    async with pg.engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT task AS task_name, lock, args FROM task_queue "
                "WHERE job_id = :job ORDER BY id"
            ),
            {"job": job_id},
        )
        return [decoded(dict(row._mapping)) for row in rows]


def active(snapshot: dict) -> list[str]:
    """The files in use; removed ones stay in the snapshot for the messages that sent them."""
    return [a["id"] for a in snapshot["attachments"] if a["active"]]


async def upload(http, job_id: str, name: str, request_id: str | None = None):
    content = Path("tests/fixtures", name).read_bytes()
    return await http.post(
        f"/api/v1/jobs/{job_id}/attachments",
        files={"file": (name, content)},
        data={"request_id": request_id or rid()},
    )


async def test_a_message_reaches_the_assistant_in_one_transaction(pg, http):
    """A message alone starts no work: the assistant decides, and only its tool does."""
    job_id = await new_job(http)
    response = await http.post(
        f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "Шестерня привода"}
    )
    assert response.json()["revision"] == 0 and response.json()["status"] == "draft"
    assert response.json()["title"] == "Шестерня привода"
    assert await queued(pg, job_id) == [
        {
            "task_name": "steer.deliver",
            "lock": f"steer:{job_id}",
            "args": {"job_id": job_id},
        }
    ]
    messages = (await http.get(f"/api/v1/jobs/{job_id}")).json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [("user", "Шестерня привода")]


async def test_repeated_command_is_idempotent_and_conflicting_reuse_is_rejected(pg, http):
    job_id = await new_job(http)
    body = {"request_id": rid(), "text": "Деталь"}
    first = await http.post(f"/api/v1/jobs/{job_id}/messages", json=body)
    second = await http.post(f"/api/v1/jobs/{job_id}/messages", json=body)
    assert first.json() == second.json() and len(await queued(pg, job_id)) == 1
    conflict = await http.post(f"/api/v1/jobs/{job_id}/messages", json={**body, "text": "Другое"})
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", ""),
        ("get", "/card"),
        ("get", "/events"),
        ("post", "/messages"),
        ("post", "/answers"),
        ("post", "/control/stop"),
    ],
)
async def test_users_never_see_each_others_jobs(http, other, method, path):
    job_id = await new_job(http)
    body = {"request_id": rid(), "text": "x", "expected_revision": 0, "answers": {"a": "b"}}
    if path.startswith("/control"):
        body = {"request_id": rid()}
    if path == "/messages":
        body = {"request_id": rid(), "text": "x"}
    if path == "/answers":
        body = {"request_id": rid(), "expected_revision": 0, "answers": {"a": "b"}}
    kwargs = {"json": body} if method == "post" else {}
    response = await getattr(other, method)(f"/api/v1/jobs/{job_id}{path}", **kwargs)
    assert response.status_code == 404
    assert job_id not in {j["id"] for j in (await other.get("/api/v1/jobs")).json()}


async def test_answers_require_current_questions(http):
    job_id = await new_job(http)
    response = await http.post(
        f"/api/v1/jobs/{job_id}/answers",
        json={"request_id": rid(), "expected_revision": 0, "answers": {"clarify.1": "да"}},
    )
    assert response.status_code == 409


async def test_an_unsent_stl_never_displaces_the_model_in_use(pg, http):
    """Regression: removing an unsent STL dropped the sent one."""
    job_id = await new_job(http)
    first = (await upload(http, job_id, "box.stl")).json()
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    second = (await upload(http, job_id, "box.stl")).json()
    third = (await upload(http, job_id, "box.stl")).json()
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert snapshot["job"]["active_stl"] == first["id"]
    # A newer unsent STL replaces the unsent one before it.
    assert active(snapshot) == sorted([first["id"], third["id"]])
    assert second["id"] not in active(snapshot)
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{third['id']}/detach", json={"request_id": rid()}
    )
    assert detached.json()["active_stl"] == first["id"]
    fourth = (await upload(http, job_id, "box.stl")).json()
    sent = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert sent.json()["active_stl"] == fourth["id"]
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert active(snapshot) == [fourth["id"]]


async def test_removing_the_sent_stl_takes_effect_on_send(pg, http):
    job_id = await new_job(http)
    first = (await upload(http, job_id, "box.stl")).json()
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{first['id']}/detach", json={"request_id": rid()}
    )
    assert detached.json()["active_stl"] == first["id"] and detached.json()["files_changed"]
    sent = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert sent.json()["active_stl"] is None


async def test_files_wait_for_an_explicit_send(pg, http):
    job_id = await new_job(http)
    await upload(http, job_id, "task.txt")
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert snapshot["job"]["files_changed"] and snapshot["job"]["revision"] == 0
    assert snapshot["attachments"][0]["status"] == "pending"
    assert await queued(pg, job_id) == []
    started = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert started.json()["revision"] == 1 and not started.json()["files_changed"]
    assert [q["args"]["revision"] for q in await queued(pg, job_id)] == [1]


async def test_unsent_files_stay_drafts_until_the_send(pg, http):
    job_id = await new_job(http)
    kept = (await upload(http, job_id, "task.txt")).json()
    dropped = (await upload(http, job_id, "photo.png")).json()
    assert kept["draft"] and dropped["draft"]
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{dropped['id']}/detach", json={"request_id": rid()}
    )
    assert detached.json()["files_changed"]
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    sent = [(a["id"], a["draft"]) for a in snapshot["attachments"] if a["active"]]
    assert sent == [(kept["id"], False)]
    assert not snapshot["job"]["files_changed"]

    extra = (await upload(http, job_id, "photo.png")).json()
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{extra['id']}/detach", json={"request_id": rid()}
    )
    assert not detached.json()["files_changed"]
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{kept['id']}/detach", json={"request_id": rid()}
    )
    assert detached.json()["files_changed"]


async def test_failed_upload_leaves_no_file_or_revision(pg, http, tmp_path):
    job_id = await new_job(http)
    response = await upload(http, job_id, "empty.txt")
    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []
    assert await queued(pg, job_id) == []


async def test_stop_is_requested_while_running_and_immediate_otherwise(pg, http):
    job_id = await new_job(http)
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id, lock=True)
        job.status = Status.RUNNING
        await uow.jobs.save(job)
        await uow.commit()
    stop = f"/api/v1/jobs/{job_id}/control/stop"
    assert (await http.post(stop, json={"request_id": rid()})).json()["status"] == "stopping"
    assert (await http.post(stop, json={"request_id": rid()})).json()["status"] == "stopping"
    retry = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert retry.json()["status"] == "queued" and retry.json()["revision"] == 2
    assert (await http.post(stop, json={"request_id": rid()})).json()["status"] == "stopped"


async def test_card_is_pending_until_stage_one_finishes(http):
    job_id = await new_job(http)
    assert (await http.get(f"/api/v1/jobs/{job_id}/card")).status_code == 409


async def test_launch_link_works_once(pg):
    import time

    import httpx

    from src.backend.api.app import create_app
    from src.backend.domain.tokens import sign_token

    app = create_app(pg.settings)
    app.state.container = pg
    token = sign_token(pg.settings.session_secret, "launch", int(time.time()) + 60, "carol")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as session:
        assert (
            await session.post("/api/v1/session/exchange", json={"token": token})
        ).status_code == 200
        assert (await session.get("/api/v1/session")).json()["user_id"] == "carol"
        again = await session.post("/api/v1/session/exchange", json={"token": token})
        assert again.status_code == 401


async def test_work_a_stopped_process_left_half_done_runs_again(pg, http):
    job_id = await new_job(http)
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    async with pg.engine.begin() as connection:
        await connection.execute(
            text("UPDATE task_queue SET status = 'doing' WHERE job_id = :job"), {"job": job_id}
        )
    handled = []

    async def stage1(job_id, revision, **flags):
        handled.append((job_id, revision))

    runner = TaskRunner(pg.uow, pg.wake, {"stage1.run": stage1}, 2)
    await runner.start()
    for _ in range(100):
        if handled:
            break
        await asyncio.sleep(0.05)
    await runner.stop()
    assert handled == [(job_id, 1)]
    async with pg.engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM task_queue WHERE job_id = :job"), {"job": job_id}
        )
    assert status == "done"


async def test_an_edit_after_a_ready_card_is_not_held_back_by_the_old_work(pg, http):
    """Work queued for an earlier revision is cancelled, and the edit runs after the stage."""
    job_id = await new_job(http)
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    # Stage one finishes the revision and hands the ready card to stage two.
    async with pg.uow() as uow:
        await uow.queue.stage2(job_id, 1)
        await uow.commit()
    # The assistant applies a correction.
    async with pg.uow() as uow:
        await changed(uow, await uow.jobs.get(job_id, lock=True), "Правка", correction=True)
        await uow.commit()
    edit = {"job_id": job_id, "revision": 2, "start": False, "correction": True}
    async with pg.engine.connect() as connection:
        rows = (
            await connection.execute(text("SELECT task, args, status FROM task_queue ORDER BY id"))
        ).all()
    assert [(task, decoded({"args": args})["args"]["revision"], status) for task, args, status in rows] == [
        ("stage1.run", 1, "cancelled"),
        ("stage2.select_parameters", 1, "cancelled"),
        ("stage1.run", 2, "todo"),
    ]
    handled = []

    async def record(**arguments):
        handled.append(arguments)

    runner = TaskRunner(pg.uow, pg.wake, {"stage1.run": record}, 2)
    await runner.start()
    for _ in range(100):
        if handled:
            break
        await asyncio.sleep(0.05)
    await runner.stop()
    assert handled == [edit]


async def test_one_job_never_runs_two_tasks_at_once(pg, http):
    job_id = await new_job(http)
    async with pg.uow() as uow:
        await uow.queue.stage1(job_id, 1)
        await uow.queue.stage2(job_id, 1)
        await uow.commit()
    active, peak, handled = 0, 0, []

    async def handler(job_id, revision, **flags):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        handled.append(job_id)

    runner = TaskRunner(pg.uow, pg.wake, {"stage1.run": handler, "stage2.select_parameters": handler}, 4)
    await runner.start()
    for _ in range(100):
        if len(handled) == 2:
            break
        await asyncio.sleep(0.05)
    await runner.stop()
    assert handled == [job_id, job_id] and peak == 1


async def test_a_delivery_runs_beside_the_stage_of_its_job_and_outlives_a_new_revision(pg, http):
    """The user's own send must not wait for the step to end, and two of them never overlap."""
    job_id = await new_job(http)
    async with pg.uow() as uow:
        await uow.queue.stage1(job_id, 1)
        await uow.queue.steer(job_id)
        await uow.queue.steer(job_id)
        # A new revision cancels the stage work queued before it, never a delivery.
        await uow.queue.cancel_pending(job_id)
        await uow.queue.stage1(job_id, 2)
        await uow.commit()
    stage_running, delivered = asyncio.Event(), asyncio.Event()
    delivering, peak, handled = 0, 0, []

    async def stage1(job_id, revision, **flags):
        stage_running.set()
        await asyncio.wait_for(delivered.wait(), 5)
        handled.append(("stage1", revision))

    async def steer(job_id):
        nonlocal delivering, peak
        delivering += 1
        peak = max(peak, delivering)
        # A delivery held behind the job's lock would wait here for a stage that never starts.
        await asyncio.wait_for(stage_running.wait(), 5)
        await asyncio.sleep(0.05)
        delivering -= 1
        handled.append(("steer", None))
        if len(handled) == 2:
            delivered.set()

    runner = TaskRunner(pg.uow, pg.wake, {"stage1.run": stage1, "steer.deliver": steer}, 4)
    await runner.start()
    for _ in range(200):
        if len(handled) == 3:
            break
        await asyncio.sleep(0.05)
    await runner.stop()
    assert handled == [("steer", None), ("steer", None), ("stage1", 2)] and peak == 1


async def test_rename_and_delete_a_chat(pg, http):
    job_id = await new_job(http)
    renamed = await http.post(
        f"/api/v1/jobs/{job_id}/rename", json={"request_id": rid(), "title": "  Колесо насоса "}
    )
    assert renamed.json()["title"] == "Колесо насоса" and renamed.json()["title_source"] == "user"
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "x"})
    assert (await http.get(f"/api/v1/jobs/{job_id}")).json()["job"]["title"] == "Колесо насоса"
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id, lock=True)
        job.status = Status.RUNNING
        await uow.jobs.save(job)
        await uow.commit()
    deleted = await http.post(f"/api/v1/jobs/{job_id}/delete", json={"request_id": rid()})
    assert deleted.json() == {"id": job_id, "deleted": True}
    assert [j["id"] for j in (await http.get("/api/v1/jobs")).json()] == []
    assert (await http.get(f"/api/v1/jobs/{job_id}")).status_code == 404
    async with pg.uow() as uow:
        assert (await uow.jobs.get(job_id)).status == Status.STOPPING


async def test_files_sent_without_a_message_name_the_chat(pg, http):
    job_id = await new_job(http)
    await upload(http, job_id, "box.stl")
    await upload(http, job_id, "task.txt")
    started = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert started.json()["title"] == "task"
