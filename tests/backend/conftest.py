import os
import time

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from src.backend.api.app import create_app
from src.backend.config import Settings
from src.backend.domain.tokens import sign_token

TEST_DATABASE = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://mosprom:mosprom_local@127.0.0.1:55432/mosprom_test"
)
TABLES = (
    "jobs, messages, attachments, events, receipts, operation_cache, knowledge, agent_calls, "
    "procrastinate_jobs, procrastinate_events"
)


@pytest_asyncio.fixture
async def pg(tmp_path):
    if not TEST_DATABASE.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("Integration tests require a database ending in _test")
    app = create_app(
        Settings(
            database_url=TEST_DATABASE,
            session_secret="test-secret-" * 4,
            data_dir=tmp_path,
            qwen_api_key="test",
            app_origin="http://localhost:8000",
        )
    )
    container = app.state.container
    async with container.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield container
    await container.close()


async def client(container, user_id: str) -> httpx.AsyncClient:
    app = create_app(container.settings)
    app.state.container = container
    session = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    )
    token = sign_token(container.settings.session_secret, "launch", int(time.time()) + 60, user_id)
    response = await session.post("/api/v1/session/exchange", json={"token": token})
    assert response.status_code == 200
    return session


@pytest_asyncio.fixture
async def http(pg):
    session = await client(pg, "alice")
    yield session
    await session.aclose()


@pytest_asyncio.fixture
async def other(pg):
    session = await client(pg, "bob")
    yield session
    await session.aclose()
