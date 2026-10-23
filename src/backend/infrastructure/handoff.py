from __future__ import annotations

import httpx

from ..domain.errors import AppError


class HttpHandoff:
    def __init__(self, url: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self.transport = transport

    async def deliver(self, key: str, card: dict) -> str:
        if not self.url:
            return "not_connected"
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                response = await client.post(
                    self.url,
                    json={"idempotency_key": key, "card": card},
                    headers={"Idempotency-Key": key},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppError(
                "Карточка сохранена, передача следующему этапу не завершена", "handoff_failed", 503
            ) from exc
        return "delivered"
