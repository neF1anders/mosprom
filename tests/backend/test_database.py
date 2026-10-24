"""The unit of work on SQLite: one writer at a time, readers beside it."""

import asyncio

import pytest
from sqlalchemy import text

from src.backend.domain.pipeline import Step

pytestmark = pytest.mark.integration


async def test_concurrent_writers_wait_for_each_other_instead_of_failing(pg):
    """Chats write in parallel; a locked database must make them queue, not raise."""

    async def write(index: int):
        async with pg.uow() as uow:
            await uow.cache.put(f"key-{index}", {"value": index})
            await asyncio.sleep(0.01)
            await uow.commit()

    await asyncio.gather(*(write(i) for i in range(20)))
    async with pg.uow() as uow:
        assert [await uow.cache.get(f"key-{i}") for i in range(20)] == [
            {"value": i} for i in range(20)
        ]


async def test_a_cancelled_request_leaves_the_pool_usable(pg):
    async def slow():
        async with pg.uow() as work:
            await work.cache.put("slow", {})
            await asyncio.sleep(5)

    task = asyncio.ensure_future(slow())
    await asyncio.sleep(0.3)
    # Starlette cancels a dropped stream level-triggered: every later await is cancelled too.
    while not task.done():
        task.cancel()
        await asyncio.sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(3):
        async with pg.uow() as work:
            assert (await work._session.execute(text("SELECT 1"))).scalar() == 1


async def test_a_step_result_is_written_once_per_revision_step_and_pass(pg):
    first, second = Step("parameters", 1), Step("parameters", 2)
    async with pg.uow() as uow:
        await uow.stage_results.add("job", 3, first, {"pass": 1})
        # A redelivered task writes the same step again; the first result stays.
        await uow.stage_results.add("job", 3, first, {"pass": "again"})
        await uow.stage_results.add("job", 3, second, {"pass": 2})
        await uow.stage_results.add("job", 4, first, {"pass": "next revision"})
        await uow.commit()
    async with pg.uow() as uow:
        assert await uow.stage_results.get("job", 3, first) == {"pass": 1}
        assert await uow.stage_results.latest("job", 3, "parameters") == {"pass": 2}
        assert await uow.stage_results.latest("job", 3, "validation") is None
        assert await uow.stage_results.get("job", 5, first) is None
