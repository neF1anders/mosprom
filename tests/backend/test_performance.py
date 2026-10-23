"""Measured bounds, not microsecond promises; output records hardware and input sizes."""

import asyncio
import json
import platform
import time
import tracemalloc
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from src.backend.domain.evidence import merge_cards
from src.backend.domain.models import Event, Requirement, TaskCard
from src.backend.infrastructure.qwen import QwenClient

pytestmark = pytest.mark.performance


def record(case, **values):
    path = Path("artifacts/performance.jsonl")
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "case": case,
                    "system": platform.platform(),
                    "processor": platform.machine(),
                    **values,
                }
            )
            + "\n"
        )


@pytest.mark.parametrize("size", [100, 500, 1000, 5000, 10000])
def test_A04_conflict_grouping_memory_and_time(size):
    requirements = [Requirement(key="size", value=str(i)) for i in range(size)]
    tracemalloc.start()
    start = time.perf_counter()
    result = merge_cards([TaskCard(requirements=requirements)])
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(result.conflicts) == 1
    assert len(result.conflicts[0].options) == size
    assert peak < size * 8000 + 1_000_000
    assert elapsed < 10
    record("A04.merge", size=size, seconds=elapsed, peak_bytes=peak)


@pytest.mark.parametrize("count", [0, 1, 10, 100, 1000])
async def test_A04_event_cursor_uses_constant_query_count(pg, count):
    job = await pg.jobs.create(str(uuid4()), "Performance")
    async with pg.uow() as uow:
        for i in range(count):
            await uow.events.append(
                Event(job_id=job["id"], revision=0, type="benchmark", status="done", message=str(i))
            )
        await uow.commit()
    queries = []

    def observed(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(pg.engine.sync_engine, "before_cursor_execute", observed)
    start = time.perf_counter()
    try:
        result = await pg.jobs.events(job["id"], max(0, count - 5))
    finally:
        event.remove(pg.engine.sync_engine, "before_cursor_execute", observed)
    assert len(queries) == 2
    assert len(result) <= 100
    assert all(e.event_id > max(0, count - 5) for e in result)
    record("A04.cursor", history=count, queries=len(queries), seconds=time.perf_counter() - start)


@pytest.mark.parametrize("operation", ["qwen", "stl", "ocr", "database", "events"])
async def test_A03_long_operation_does_not_block_health(pg, http, operation):
    started = asyncio.Event()
    release = asyncio.Event()

    async def provider(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = QwenClient("http://test", "test", "test", transport=httpx.MockTransport(provider))

    async def work():
        if operation == "qwen":
            await client.complete([], [])
            return
        if operation == "database":
            async with pg.engine.connect() as conn:
                started.set()
                await conn.execute(text("select pg_sleep(0.3)"))
            return
        if operation == "events":
            job = await pg.jobs.create(str(uuid4()), "Events")
            started.set()
            await asyncio.gather(*(pg.jobs.events(job["id"]) for _ in range(8)))
            return
        file = Path("tests/fixtures/box.stl" if operation == "stl" else "tests/fixtures/scan.pdf")
        key = str(uuid4())

        async def chunks():
            yield file.read_bytes()

        await pg.files.put(key, chunks(), 30 * 1024 * 1024)
        started.set()
        if operation == "stl":
            await pg.files.analyze(key, "mm", str(uuid4()))
        else:
            await pg.files.inspect(key, "pdf")

    task = asyncio.create_task(work())
    await started.wait()
    begin = time.perf_counter()
    responses = await asyncio.gather(*(http.get("/api/v1/health") for _ in range(5)))
    latency = time.perf_counter() - begin
    release.set()
    await task
    await client.close()
    assert all(r.status_code == 200 for r in responses)
    assert latency < 2
    record("A03.responsiveness", operation=operation, commands=5, seconds=latency)


@pytest.mark.parametrize("subdivisions", [1, 2, 3, 4, 5])
def test_A04_increasing_geometry_preserves_bounds(tmp_path, subdivisions):
    import trimesh

    from src.mesh_analysis import analyze_stl

    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=10)
    path = tmp_path / "sphere.stl"
    mesh.export(path)
    tracemalloc.start()
    begin = time.perf_counter()
    report = analyze_stl(path, units="mm", samples=0)
    elapsed = time.perf_counter() - begin
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert report["geometry"]["extents"] == pytest.approx([20, 20, 20])
    assert report["topology"]["component_count"] == 1
    assert elapsed < 30
    assert peak < len(mesh.faces) * 20_000 + 50_000_000
    record(
        "A04.geometry",
        triangles=len(mesh.faces),
        seconds=elapsed,
        peak_python_bytes=peak,
        ray_samples=0,
    )
