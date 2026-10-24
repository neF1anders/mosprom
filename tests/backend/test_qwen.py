import json

import httpx
import pytest

from src.backend.domain.errors import AppError
from src.backend.infrastructure.qwen import QwenClient

pytestmark = pytest.mark.unit


def client(respond) -> QwenClient:
    return QwenClient(
        "http://test/v1", "test-model", "key", transport=httpx.MockTransport(respond), retry_delay=0
    )


@pytest.mark.parametrize("status,attempts", [(429, 3), (500, 3), (503, 3), (401, 1), (400, 1)])
async def test_retry_budget(status, attempts):
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "test"}, headers={"Retry-After": "0"})

    qwen = client(respond)
    with pytest.raises(AppError):
        await qwen.complete([{"role": "user", "content": "test"}], [], agent="a", thinking=False)
    assert len(calls) == attempts
    await qwen.close()


async def test_transport_timeout_retried_twice():
    calls = []

    async def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout")

    qwen = client(respond)
    with pytest.raises(AppError) as error:
        await qwen.complete([], [], agent="a", thinking=False)
    assert error.value.code == "model_unavailable"
    assert len(calls) == 3
    await qwen.close()


async def test_reply_keeps_reasoning_usage_and_raw_provider_answer():
    sent = {}
    body = {
        "id": "x",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": "{}", "reasoning_content": "думаю", "tool_calls": None},
            }
        ],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 5}},
    }

    async def respond(request):
        sent["agent"] = request.headers["X-Mosprom-Agent"]
        sent["payload"] = json.loads(request.content)
        return httpx.Response(200, json=body)

    qwen = client(respond)
    reply = await qwen.complete([], [], agent="judge", thinking=True)
    assert (reply.content, reply.reasoning, reply.finish_reason) == ("{}", "думаю", "stop")
    assert reply.tool_calls == [] and reply.raw == body
    assert sent["agent"] == "judge" and sent["payload"]["enable_thinking"] is True
    assert "tools" not in sent["payload"]
    await qwen.close()


async def test_missing_key_is_reported_without_a_request():
    qwen = QwenClient("http://test", "m", "")
    with pytest.raises(AppError) as error:
        await qwen.complete([], [], agent="a", thinking=False)
    assert error.value.code == "model_not_configured"
    await qwen.close()


def stream(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


async def test_stream_joins_reasoning_text_tool_calls_and_usage():
    sent = {}
    body = stream(
        {"id": "s1", "model": "m", "choices": [{"delta": {"reasoning_content": "ду"}}]},
        {"choices": [{"delta": {"reasoning_content": "маю", "content": '{"a"'}}]},
        {"choices": [{"delta": {"content": ": 1}"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "t1", "function": {"name": "convert_units"}}
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"v":'}}]},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"total_tokens": 7}},
    )

    async def respond(request):
        sent["payload"] = json.loads(request.content)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    qwen = client(respond)
    reply = await qwen.complete([], [], agent="a", thinking=True, budget=900)
    assert (reply.content, reply.reasoning, reply.finish_reason) == (
        '{"a": 1}',
        "думаю",
        "tool_calls",
    )
    assert reply.tool_calls == [
        {
            "id": "t1",
            "type": "function",
            "function": {"name": "convert_units", "arguments": '{"v":1}'},
        }
    ]
    assert reply.usage == {"total_tokens": 7} and reply.raw["usage"] == {"total_tokens": 7}
    assert reply.raw["choices"][0]["message"]["content"] == '{"a": 1}'
    assert sent["payload"]["stream"] is True and sent["payload"]["thinking_budget"] == 900
    await qwen.close()


async def test_stream_cut_before_finish_is_retried():
    calls = []
    partial = stream({"choices": [{"delta": {"content": "{"}}]})

    async def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200, content=partial, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(
            200,
            content=stream({"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]}),
            headers={"content-type": "text/event-stream"},
        )

    qwen = client(respond)
    reply = await qwen.complete([], [], agent="a", thinking=False)
    assert reply.content == "{}" and len(calls) == 2
    await qwen.close()


async def test_budget_is_sent_only_with_thinking():
    sent = {}

    async def respond(request):
        sent["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    qwen = client(respond)
    await qwen.complete([], [], agent="a", thinking=False, budget=900)
    assert "thinking_budget" not in sent["payload"]
    await qwen.close()
