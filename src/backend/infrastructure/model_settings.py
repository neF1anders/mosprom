from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from ..domain.model_settings import ModelSettings

logger = logging.getLogger(__name__)
FIELDS = ("base_url", "model", "api_key")


class ModelSettingsFile:
    """The settings saved from the chat, in DATA_DIR.

    A value the file lacks comes from env, which the portable build's plugin fills from its
    own settings. The file is read again only when it changes, so a save reaches the next
    model call.
    """

    def __init__(self, folder: Path, defaults: ModelSettings):
        self.path, self.defaults = folder / "model.json", defaults
        self._seen: tuple[tuple[int, int, int], ModelSettings] | None = None

    def current(self) -> ModelSettings:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return self.defaults
        # A save replaces the file, so a new inode tells it apart even within one mtime tick.
        stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        if self._seen is None or self._seen[0] != stamp:
            self._seen = stamp, self._read()
        return self._seen[1]

    def update(self, base_url: str, model: str, api_key: str | None) -> ModelSettings:
        settings = self.current().updated(base_url, model, api_key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid4().hex}")
        # Only the owner reads the key; the other process sees the old file or the new one.
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(asdict(settings), stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return settings

    def _read(self) -> ModelSettings:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Model settings %s are unreadable, env values apply", self.path)
            return self.defaults
        if not isinstance(saved, dict):
            return self.defaults
        values = {key: saved[key] for key in FIELDS if isinstance(saved.get(key), str)}
        return replace(self.defaults, **{key: text for key, text in values.items() if text})
