from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain.limits import InputLimits


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_nested_delimiter="__")
    limits: InputLimits = InputLimits()
    database_url: str = "postgresql+psycopg://mosprom:mosprom_local@127.0.0.1:55432/mosprom"
    data_dir: Path = Path("artifacts/stage1")
    # The issued STE Slicer build and the printer whose parameters are selected.
    build_dir: Path = Path("knowledge/ste_5.2.4")
    printer: str = "hte530v5.2.4"
    requirement_keys_path: Path = Path("knowledge/requirement_keys.json")
    qwen_base_url: str = "https://api.timeweb.ai/v1"
    qwen_model: str = "dashscope/qwen3.8-flash"
    qwen_api_key: str = ""
    qwen_max_tokens: int = Field(default=32768, ge=1024, le=131072)
    # Stage one targets five minutes; a run three times longer is stuck, not slow.
    stage1_timeout_seconds: float = Field(default=900, gt=0)
    # The model reasons in English; a narrator tells the chat in Russian what an agent does.
    narrate_reasoning: bool = True
    # Selection and its check take well under a second; a minute means something is stuck.
    parameters_timeout_seconds: float = Field(default=60, gt=0)
    # STE Slicer with the AI Assistant plugin: the folder of its server.json, shared with the
    # worker for models and results; ``slicer_host_folder`` is that folder as the slicer sees
    # it when the worker runs in Docker, and ``slicer_host`` where its port is reached.
    slicer_folder: Path = Path.home() / "Documents" / "STE_AIAssistant"
    slicer_host_folder: str = ""
    slicer_host: str = "127.0.0.1"
    # The plugin waits up to five minutes for a slicing, loading and saving add a minute.
    slicing_timeout_seconds: float = Field(default=420, gt=0)
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    app_origin: str = "http://localhost:8000"
    session_secret: str = ""
