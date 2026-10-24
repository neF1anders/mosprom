"""The OpenAI-compatible API the agents call, entered in the chat or taken from env."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import AppError


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def updated(self, base_url: str, model: str, api_key: str | None) -> ModelSettings:
        """The user's entry over these settings; an empty key keeps the current one."""
        base_url, model, api_key = base_url.strip(), model.strip(), (api_key or "").strip()
        if not http_url(base_url):
            raise AppError("Укажите адрес API в виде http или https")
        if not model:
            raise AppError("Укажите имя модели")
        if not (api_key or self.api_key):
            raise AppError("Укажите API ключ")
        return ModelSettings(base_url, model, api_key or self.api_key)


def http_url(text: str) -> bool:
    if any(char.isspace() for char in text):
        return False
    try:
        parts = urlsplit(text)
        # A port that is not a number fails here rather than at the first model call.
        return parts.scheme in ("http", "https") and bool(parts.hostname) and parts.port != 0
    except ValueError:
        return False
