from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain.limits import InputLimits


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_nested_delimiter="__")
    limits: InputLimits = InputLimits()
    database_url: str = "postgresql+asyncpg://mosprom:mosprom_local@127.0.0.1:55432/mosprom"
    data_dir: Path = Path("artifacts/stage1")
    qwen_base_url: str = "https://api.timeweb.ai/v1"
    qwen_model: str = "dashscope/qwen3.8-flash"
    qwen_api_key: str = ""
    app_origin: str = "http://localhost:8000"
    session_secret: str = ""
    handoff_url: str = ""
