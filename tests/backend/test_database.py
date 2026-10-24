"""The unit of work on PostgreSQL: a cancelled request must not poison the connection pool."""

import asyncio

import pytest
from sqlalchemy import text

from src.backend.infrastructure.database import database
from src.backend.infrastructure.queue import queue_app

from .conftest import TEST_DATABASE

pytestmark = pytest.mark.integration


async def test_a_query_cancelled_mid_flight_leaves_the_pool_usable():
    """A stop now cancels a run even mid-query, and a closed event stream cancels its read;
    neither may hand the next request a connection still busy with the cancelled statement."""
    engine, uow = database(TEST_DATABASE, queue_app(TEST_DATABASE))
    try:

        async def slow():
            async with uow() as work:
                await work._session.execute(text("SELECT pg_sleep(5)"))

        task = asyncio.ensure_future(slow())
        await asyncio.sleep(0.5)
        # Starlette cancels a dropped stream level-triggered: every later await is cancelled too.
        while not task.done():
            task.cancel()
            await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(3):
            async with uow() as work:
                assert (await work._session.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await engine.dispose()
