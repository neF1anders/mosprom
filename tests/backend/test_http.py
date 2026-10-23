import httpx
import pytest

from src.backend.api.app import create_app
from src.backend.config import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/jobs",
        "/api/v1/jobs/fake",
        "/api/v1/jobs/fake/card",
        "/api/v1/jobs/fake/events",
        "/api/v1/jobs/fake/artifacts/fake",
    ],
)
async def test_protected_routes_need_session(path, tmp_path):
    app = create_app(Settings(session_secret="x" * 40, data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        response = await client.get(path)
        assert response.status_code == 401
    await app.state.container.close()
