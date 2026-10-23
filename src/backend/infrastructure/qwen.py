from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..domain.errors import AppError


class QwenClient:
    def __init__(
        self, base_url: str, model: str, api_key: str, *, transport=None, retry_delay: float = 1
    ):
        self.model, self.api_key, self.retry_delay = model, api_key, retry_delay
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(120, connect=15),
            transport=transport,
            limits=httpx.Limits(max_connections=4),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not self.api_key:
            raise AppError("Ключ Qwen не настроен на сервере", "model_not_configured", 503)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 8192,
            "enable_thinking": False,
        }
        if tools:
            payload["tools"] = tools
        for attempt in range(3):
            response = await self._request(payload)
            if response is not None and response.is_success:
                return self._decode(response)
            if response is not None and response.status_code < 500 and response.status_code != 429:
                code = (
                    "context_limit"
                    if response.status_code == 400 and "context" in response.text.casefold()
                    else "model_request_error"
                )
                raise AppError("API модели отклонил запрос, проверьте настройки сервера", code, 502)
            if attempt < 2:
                await asyncio.sleep(self._delay(response, attempt))
        raise AppError(
            "Модель недоступна после трёх попыток, можно повторить позже", "model_unavailable", 503
        )

    async def _request(self, payload: dict[str, Any]) -> httpx.Response | None:
        try:
            return await self.client.post(
                "chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.TransportError:
            return None

    def _delay(self, response: httpx.Response | None, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "") if response is not None else ""
        try:
            return min(60, max(0, float(raw)))
        except ValueError:
            pass
        try:
            return min(
                60,
                max(0, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()),
            )
        except (ValueError, TypeError):
            return self.retry_delay * 2**attempt

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
            message = data["choices"][0]["message"]
            return {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls", []),
                "usage": data.get("usage", {}),
            }
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AppError("API вернул непонятный ответ", "model_protocol_error", 502) from exc
