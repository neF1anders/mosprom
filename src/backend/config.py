from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain.limits import InputLimits


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_nested_delimiter="__")
    limits: InputLimits = InputLimits()
    # пусто значит app.db
    database_url: str = ""
    data_dir: Path = Path("artifacts/stage1")
    # сборка и принтер
    build_dir: Path = Path("knowledge/ste_5.2.4")
    printer: str = "hte530v5.2.4"
    requirement_keys_path: Path = Path("knowledge/requirement_keys.json")
    qwen_base_url: str = "https://api.timeweb.ai/v1"
    qwen_model: str = "dashscope/qwen3.8-flash"
    qwen_api_key: str = ""
    qwen_max_tokens: int = Field(default=32768, ge=1024, le=131072)
    # предел первого этапа
    stage1_timeout_seconds: float = Field(default=900, gt=0)
    # рассказчик по-русски
    narrate_reasoning: bool = True
    # предел подбора
    parameters_timeout_seconds: float = Field(default=60, gt=0)
    # папка плагина слайсера
    slicer_folder: Path = Path.home() / "Documents" / "STE_AIAssistant"
    slicer_host_folder: str = ""
    slicer_host: str = "127.0.0.1"
    # предел нарезки
    slicing_timeout_seconds: float = Field(default=420, gt=0)
    # число параллельных этапов
    worker_concurrency: int = Field(default=4, ge=1, le=32)
    app_origin: str = "http://localhost:8000"
    session_secret: str = ""
    # родитель плагина
    parent_pid: int = 0

    @model_validator(mode="after")
    def default_database(self) -> "Settings":
        if not self.database_url:
            self.database_url = "sqlite+aiosqlite:///" + (self.data_dir / "app.db").as_posix()
        return self
