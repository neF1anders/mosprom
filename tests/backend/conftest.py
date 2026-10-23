import os

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from src.backend.api.app import create_app
from src.backend.config import Settings
from src.backend.domain.tokens import sign_token

TEST_DATABASE = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://mosprom:mosprom_local@127.0.0.1:55432/mosprom_test"
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
        await connection.execute(
            text(
                "TRUNCATE jobs, messages, attachments, events, receipts, operation_cache, cards, work_queue, knowledge RESTART IDENTITY"
            )
        )
    yield container
    await container.close()


@pytest_asyncio.fixture
async def http(pg):
    import time

    app = create_app(pg.settings)
    app.state.container = pg
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        token = sign_token(pg.settings.session_secret, "launch", int(time.time()) + 60)
        response = await client.post("/api/v1/session/exchange", json={"token": token})
        assert response.status_code == 200
        yield client
    await app.state.container.close()
