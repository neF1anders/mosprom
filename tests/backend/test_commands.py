"""HTTP commands against PostgreSQL: atomic revisions, queueing, ownership, idempotency."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.backend.domain.models import Status

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
                "SELECT task_name, queue_name, lock, args FROM procrastinate_jobs "
                "WHERE args->>'job_id' = :job ORDER BY id"
            ),
            {"job": job_id},
        )
        return [dict(row._mapping) for row in rows]


async def upload(http, job_id: str, name: str, request_id: str | None = None):
    content = Path("tests/fixtures", name).read_bytes()
    return await http.post(
        f"/api/v1/jobs/{job_id}/attachments",
        files={"file": (name, content)},
        data={"request_id": request_id or rid()},
    )


async def test_message_creates_revision_and_queues_work_in_one_transaction(pg, http):
    job_id = await new_job(http)
    response = await http.post(
        f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "Шестерня привода"}
    )
    assert response.json()["revision"] == 1 and response.json()["status"] == "queued"
    assert response.json()["title"] == "Шестерня привода"
    assert await queued(pg, job_id) == [
        {
            "task_name": "stage1.run",
            "queue_name": "stage1",
            "lock": f"job:{job_id}",
            "args": {"job_id": job_id, "revision": 1},
        }
    ]


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
        json={"request_id": rid(), "expected_revision": 0, "answers": {"units": "mm"}},
    )
    assert response.status_code == 409


async def test_an_unsent_stl_never_displaces_the_model_in_use(pg, http):
    """Regression: removing an unsent STL dropped the sent one and its confirmed scale."""
    job_id = await new_job(http)
    first = (await upload(http, job_id, "box.stl")).json()
    await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    async with pg.uow() as uow:
        job = await uow.jobs.get(job_id, lock=True)
        job.units = "mm"
        await uow.jobs.save(job)
        await uow.commit()
    second = (await upload(http, job_id, "box.stl")).json()
    third = (await upload(http, job_id, "box.stl")).json()
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert (snapshot["job"]["active_stl"], snapshot["job"]["units"]) == (first["id"], "mm")
    # A newer unsent STL replaces the unsent one before it.
    assert [a["id"] for a in snapshot["attachments"]] == sorted([first["id"], third["id"]])
    assert second["id"] not in {a["id"] for a in snapshot["attachments"]}
    detached = await http.post(
        f"/api/v1/jobs/{job_id}/attachments/{third['id']}/detach", json={"request_id": rid()}
    )
    assert (detached.json()["active_stl"], detached.json()["units"]) == (first["id"], "mm")
    fourth = (await upload(http, job_id, "box.stl")).json()
    sent = await http.post(f"/api/v1/jobs/{job_id}/control/retry", json={"request_id": rid()})
    assert (sent.json()["active_stl"], sent.json()["units"]) == (fourth["id"], "unknown")
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert [a["id"] for a in snapshot["attachments"]] == [fourth["id"]]


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
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "x"})
    snapshot = (await http.get(f"/api/v1/jobs/{job_id}")).json()
    assert [(a["id"], a["draft"]) for a in snapshot["attachments"]] == [(kept["id"], False)]
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
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "x"})
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


async def test_job_of_a_dead_worker_returns_to_the_queue(pg, http):
    from src.backend.worker import retry_stalled

    job_id = await new_job(http)
    await http.post(f"/api/v1/jobs/{job_id}/messages", json={"request_id": rid(), "text": "x"})
    async with pg.engine.begin() as connection:
        worker = await connection.scalar(
            text(
                "INSERT INTO procrastinate_workers (last_heartbeat) "
                "VALUES (NOW() - INTERVAL '5 minutes') RETURNING id"
            )
        )
        await connection.execute(
            text(
                "UPDATE procrastinate_jobs SET status = 'doing', worker_id = :worker "
                "WHERE args->>'job_id' = :job"
            ),
            {"worker": worker, "job": job_id},
        )
    async with pg.queue.open_async():
        assert await retry_stalled(pg.queue) == 1
        assert await retry_stalled(pg.queue) == 0
    async with pg.engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM procrastinate_jobs WHERE args->>'job_id' = :job"),
            {"job": job_id},
        )
    assert status == "todo"


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
