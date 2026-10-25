import json
import os
import stat
import time

import httpx
import pytest

from src.backend.api.app import create_app
from src.backend.config import Settings
from src.backend.domain.errors import AppError
from src.backend.domain.model_settings import ModelSettings
from src.backend.domain.tokens import sign_token
from src.backend.infrastructure.model_settings import ModelSettingsFile

from .conftest import TEST_DATABASE

pytestmark = pytest.mark.unit
ENV = ModelSettings("https://env.example/v1", "env-model", "env-key")


def test_env_values_apply_until_the_chat_saves_others(tmp_path):
    assert ModelSettingsFile(tmp_path, ENV).current() == ENV


def test_the_saved_file_wins_and_reaches_another_process(tmp_path):
    saved = ModelSettingsFile(tmp_path, ENV)
    other = ModelSettingsFile(tmp_path, ENV)
    assert other.current() == ENV
    result = saved.update(" http://local:8101/v1 ", " my-model ", " my-key ")
    assert result == ModelSettings("http://local:8101/v1", "my-model", "my-key")
    assert "my-key" not in repr(result)
    assert other.current() == result
    saved.update("http://local:8101/v1", "next-model", "next-key")
    assert other.current().model == "next-model"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_an_empty_key_keeps_the_saved_one(tmp_path, key):
    saved = ModelSettingsFile(tmp_path, ModelSettings("https://env.example/v1", "m", ""))
    saved.update("https://first.example/v1", "first", "secret")
    assert saved.update("https://second.example/v1", "second", key) == ModelSettings(
        "https://second.example/v1", "second", "secret"
    )


def test_an_empty_key_keeps_the_env_one(tmp_path):
    assert ModelSettingsFile(tmp_path, ENV).update("http://x/v1", "m", None).api_key == "env-key"


@pytest.mark.parametrize(
    ("base_url", "model", "key", "message"),
    [
        ("", "m", "k", "Укажите адрес API в виде http или https"),
        ("ftp://host/v1", "m", "k", "Укажите адрес API в виде http или https"),
        ("api.example.com/v1", "m", "k", "Укажите адрес API в виде http или https"),
        ("http://", "m", "k", "Укажите адрес API в виде http или https"),
        ("http://host:port/v1", "m", "k", "Укажите адрес API в виде http или https"),
        ("http://ho st/v1", "m", "k", "Укажите адрес API в виде http или https"),
        ("http://[::1/v1", "m", "k", "Укажите адрес API в виде http или https"),
        ("http://host/v1", "  ", "k", "Укажите имя модели"),
        ("http://host/v1", "m", None, "Укажите API ключ"),
    ],
)
def test_a_wrong_entry_is_refused_and_nothing_is_saved(tmp_path, base_url, model, key, message):
    saved = ModelSettingsFile(tmp_path, ModelSettings("https://env.example/v1", "env-model", ""))
    with pytest.raises(AppError) as error:
        saved.update(base_url, model, key)
    assert (error.value.message, error.value.code, error.value.status) == (
        message,
        "invalid_input",
        422,
    )
    assert list(tmp_path.iterdir()) == []


def test_the_file_is_replaced_whole_and_only_the_owner_reads_it(tmp_path):
    ModelSettingsFile(tmp_path, ENV).update("http://x/v1", "m", "secret")
    assert [path.name for path in tmp_path.iterdir()] == ["model.json"]
    stored = json.loads((tmp_path / "model.json").read_text(encoding="utf-8"))
    assert stored == {"base_url": "http://x/v1", "model": "m", "api_key": "secret"}
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "model.json").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{not json", ENV),
        ("[]", ENV),
        ('{"model": "saved", "api_key": ""}', ModelSettings(ENV.base_url, "saved", ENV.api_key)),
        ('{"base_url": 5, "model": null}', ENV),
    ],
)
def test_a_damaged_file_falls_back_to_env(tmp_path, content, expected):
    (tmp_path / "model.json").write_text(content, encoding="utf-8")
    assert ModelSettingsFile(tmp_path, ENV).current() == expected


def app_settings(tmp_path, **values) -> Settings:
    return Settings(
        _env_file=None,
        session_secret="x" * 40,
        data_dir=tmp_path,
        database_url=TEST_DATABASE,
        **values,
    )


async def call(settings: Settings, requests) -> list[httpx.Response]:
    app = create_app(settings)
    session = sign_token(settings.session_secret, "session", int(time.time()) + 60, "alice")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8000",
        cookies={"mosprom_session": session},
    ) as client:
        responses = [
            await client.request(method, path, json=body) for method, path, body in requests
        ]
    await app.state.container.close()
    return responses


async def test_the_chat_sees_the_settings_but_never_the_key(tmp_path):
    settings = app_settings(tmp_path, qwen_api_key="env-secret")
    model, capabilities = await call(
        settings, [("GET", "/api/v1/model", None), ("GET", "/api/v1/capabilities", None)]
    )
    assert model.json() == {
        "base_url": settings.qwen_base_url,
        "model": settings.qwen_model,
        "api_key_set": True,
        "configured": True,
    }
    assert "env-secret" not in model.text
    assert capabilities.json()["model_configured"] is True


async def test_a_save_in_the_chat_connects_the_model(tmp_path):
    settings = app_settings(tmp_path, qwen_api_key="")
    entry = {"base_url": "https://api.example/v1", "model": "m", "api_key": "secret"}
    before, saved, kept, capabilities = await call(
        settings,
        [
            ("GET", "/api/v1/capabilities", None),
            ("POST", "/api/v1/model", {**entry, "request_id": "r1"}),
            ("POST", "/api/v1/model", {**entry, "model": "m2", "api_key": None}),
            ("GET", "/api/v1/capabilities", None),
        ],
    )
    assert before.json()["model_configured"] is False
    assert saved.status_code == 200 and "secret" not in saved.text
    assert saved.json() == {
        "base_url": "https://api.example/v1",
        "model": "m",
        "api_key_set": True,
        "configured": True,
    }
    assert kept.json()["model"] == "m2" and kept.json()["api_key_set"] is True
    assert capabilities.json()["model_configured"] is True
    stored = json.loads((tmp_path / "model.json").read_text(encoding="utf-8"))
    assert stored["api_key"] == "secret"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"base_url": "localhost:8101", "model": "m", "api_key": "k"}, "Укажите адрес API"),
        ({"base_url": "http://x/v1", "model": "", "api_key": "k"}, "Укажите имя модели"),
        ({"base_url": "http://x/v1", "model": "m"}, "Укажите API ключ"),
        ({}, "Укажите адрес API"),
    ],
)
async def test_a_wrong_entry_is_explained(tmp_path, body, message):
    settings = app_settings(tmp_path, qwen_api_key="")
    (response,) = await call(settings, [("POST", "/api/v1/model", body)])
    assert response.status_code == 422
    assert response.json()["error"].startswith(message)
    assert response.json()["code"] == "invalid_input"
    assert not (tmp_path / "model.json").exists()
