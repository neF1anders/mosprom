from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any

import httpx

from ..domain.errors import AppError
from ..domain.model_settings import ModelSettings
from ..ports.operations import ModelReply, Reasoning

logger = logging.getLogger(__name__)


class _Transient(Exception):
    """A failure worth another attempt: nothing usable arrived from the provider."""

    def __init__(self, reason: str, response: httpx.Response | None = None):
        super().__init__(reason)
        self.response = response


class QwenClient:
    """Streams every completion, so silence means a stuck provider rather than a long answer."""

    def __init__(
        self,
        settings: Callable[[], ModelSettings],
        *,
        max_tokens: int = 32768,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay: float = 1,
        silence_seconds: float = 120,
        call_seconds: float = 600,
    ):
        # Read at every call: the address, model and key saved in the chat apply at once.
        self.settings, self.retry_delay = settings, retry_delay
        self.max_tokens, self.call_seconds = max_tokens, call_seconds
        self.client = httpx.AsyncClient(
            # read bounds the wait for the first token (provider queue) and every gap after it.
            timeout=httpx.Timeout(silence_seconds, connect=15),
            transport=transport,
            limits=httpx.Limits(max_connections=8),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        agent: str,
        thinking: bool,
        budget: int | None = None,
        on_reasoning: Reasoning | None = None,
    ) -> ModelReply:
        settings = self.settings()
        if not settings.configured:
            raise AppError(
                "LLM модель не подключена, укажите адрес API, модель и ключ",
                "model_not_configured",
                503,
            )
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "enable_thinking": thinking,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if thinking and budget:
            payload["thinking_budget"] = budget
        if tools:
            payload["tools"] = tools
        # Transient failures get two retries after the original attempt; others fail at once.
        for attempt in range(3):
            think = partial(_forward, on_reasoning, attempt + 1)
            try:
                async with asyncio.timeout(self.call_seconds):
                    return await self._request(settings, payload, agent, think)
            except TimeoutError as exc:
                # A stream still going after the call budget would only repeat on retry.
                logger.warning("Model call %s exceeded %ss", agent, self.call_seconds)
                raise AppError(
                    "Модель отвечает слишком долго, попробуйте позже", "model_timeout", 504
                ) from exc
            except _Transient as exc:
                logger.warning("Model call %s attempt %d failed: %s", agent, attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(self._delay(exc.response, attempt))
        raise AppError("Модель не отвечает, попробуйте позже", "model_unavailable", 503)

    async def _request(
        self,
        settings: ModelSettings,
        payload: dict[str, Any],
        agent: str,
        think: Callable[[str], Awaitable[None]],
    ) -> ModelReply:
        url = settings.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {settings.api_key}", "X-Mosprom-Agent": agent}
        try:
            async with self.client.stream("POST", url, json=payload, headers=headers) as response:
                if not response.is_success:
                    await response.aread()
                    if response.status_code < 500 and response.status_code != 429:
                        raise AppError(
                            "API модели отклонил запрос, проверьте адрес API, модель и ключ",
                            "model_request_error",
                            502,
                        )
                    raise _Transient(f"HTTP {response.status_code}", response)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    # Providers that ignore stream answer with a single JSON body.
                    await response.aread()
                    reply = self._decode(response.content)
                    await think(reply.reasoning)
                    return reply
                return await self._collect(response, think)
        except httpx.TransportError as exc:
            raise _Transient(type(exc).__name__) from exc

    async def _collect(
        self, response: httpx.Response, think: Callable[[str], Awaitable[None]]
    ) -> ModelReply:
        """Joins SSE deltas into the same reply a non-streaming call returns.

        The reasoning is handed on as it arrives, so the chat can show it before the answer.
        """
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish = ""
        usage: dict[str, Any] = {}
        head: dict[str, Any] = {}
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError as exc:
                raise AppError("API вернул непонятный ответ", "model_protocol_error", 502) from exc
            if "error" in chunk:
                raise _Transient(f"stream error {str(chunk['error'])[:200]}")
            head = head or {k: chunk[k] for k in ("id", "model", "created") if k in chunk}
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                content.append(delta.get("content") or "")
                thought = delta.get("reasoning_content") or ""
                reasoning.append(thought)
                await think(thought)
                for part in delta.get("tool_calls") or []:
                    call = calls.setdefault(
                        part.get("index", len(calls)),
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    call["id"] = part.get("id") or call["id"]
                    function = part.get("function") or {}
                    call["function"]["name"] += function.get("name") or ""
                    call["function"]["arguments"] += function.get("arguments") or ""
                finish = choice.get("finish_reason") or finish
        if not finish:
            raise _Transient("stream ended without finish_reason")
        tool_calls = [calls[index] for index in sorted(calls)]
        text, thought = "".join(content), "".join(reasoning)
        message = {
            "role": "assistant",
            "content": text,
            "tool_calls": tool_calls or None,
            "reasoning_content": thought,
        }
        raw = {
            **head,
            "object": "chat.completion",
            "usage": usage,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        }
        return ModelReply(
            content=text,
            tool_calls=tool_calls,
            finish_reason=finish,
            reasoning=thought,
            usage=usage,
            raw=raw,
        )

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
    def _decode(body: bytes) -> ModelReply:
        try:
            data = json.loads(body)
            choice = data["choices"][0]
            message = choice["message"]
            return ModelReply(
                content=message.get("content") or "",
                tool_calls=message.get("tool_calls") or [],
                finish_reason=choice.get("finish_reason") or "",
                reasoning=message.get("reasoning_content") or "",
                usage=data.get("usage") or {},
                raw=data,
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AppError("API вернул непонятный ответ", "model_protocol_error", 502) from exc


async def _forward(on_reasoning: Reasoning | None, attempt: int, text: str) -> None:
    """Hands a piece of the reasoning to the caller, if it listens and the piece has text."""
    if text and on_reasoning is not None:
        await on_reasoning(text, attempt)
