import time

import httpx
import pytest

from src.backend.api.app import create_app
from src.backend.config import Settings
from src.backend.domain.tokens import sign_token

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/jobs",
        "/api/v1/jobs/fake",
        "/api/v1/jobs/fake/card",
        "/api/v1/jobs/fake/events",
        "/api/v1/jobs/fake/artifacts/fake",
        "/api/v1/model",
    ],
)
async def test_protected_routes_need_session(path, tmp_path):
    app = create_app(Settings(_env_file=None, session_secret="x" * 40, data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        response = await client.get(path)
        assert response.status_code == 401
    await app.state.container.close()


@pytest.mark.parametrize(
    ("host_folder", "exists", "expected"),
    [
        (
            r"C:\Users\me\Documents\STE_AIAssistant",
            False,
            r"C:\Users\me\Documents\STE_AIAssistant\Результаты",
        ),
        ("", True, "slicer"),
        ("", False, None),
    ],
)
async def test_capabilities_name_the_folder_of_saved_projects(
    host_folder, exists, expected, tmp_path
):
    """Папка проектов в возможностях."""
    folder = tmp_path / "slicer"
    if exists:
        folder.mkdir()
    settings = Settings(
        _env_file=None,
        session_secret="x" * 40,
        data_dir=tmp_path,
        slicer_folder=folder,
        slicer_host_folder=host_folder,
    )
    app = create_app(settings)
    session = sign_token(settings.session_secret, "session", int(time.time()) + 60, "alice")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8000",
        cookies={"mosprom_session": session},
    ) as client:
        found = (await client.get("/api/v1/capabilities")).json()["project_folder"]
    await app.state.container.close()
    assert found == (str(folder / "Результаты") if expected == "slicer" else expected)
