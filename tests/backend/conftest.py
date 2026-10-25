import json
import time

import httpx
import pytest_asyncio

from src.backend.api.app import create_app
from src.backend.config import Settings
from src.backend.domain.tokens import sign_token
from src.backend.infrastructure.database import create_schema

JSON_COLUMNS = {"payload", "response", "request", "tools", "result", "aliases", "args"}


def decoded(row: dict) -> dict:
    """Raw SQL returns JSON columns as text; the application reads them as values."""
    return {
        k: json.loads(v) if k in JSON_COLUMNS and isinstance(v, str) else v
        for k, v in row.items()
    }


@pytest_asyncio.fixture
async def pg(tmp_path, tmp_path_factory):
    """The app's container on a fresh SQLite file; the runner stays off unless a test starts it."""
    app = create_app(
        Settings(
            # The developer's .env, with its real slicer folder, never reaches a test.
            _env_file=None,
            database_url="sqlite+aiosqlite:///" + (tmp_path_factory.mktemp("db") / "test.db").as_posix(),
            session_secret="test-secret-" * 4,
            data_dir=tmp_path,
            # No slicer runs here unless a test starts the stand-in in this folder.
            slicer_folder=tmp_path / "slicer",
            qwen_api_key="test",
            app_origin="http://localhost:8000",
            # Scripted replies go to the agents in order; a narrator would take some of them.
            narrate_reasoning=False,
        )
    )
    container = app.state.container
    await create_schema(container.engine)
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
