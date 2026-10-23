import httpx
import pytest

from src.backend.domain.errors import AppError
from src.backend.infrastructure.qwen import QwenClient

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status,attempts", [(429, 3), (500, 3), (503, 3), (401, 1), (400, 1)])
async def test_T10_retry_budget(status, attempts):
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "test"}, headers={"Retry-After": "0"})

    client = QwenClient(
        "http://test/v1",
        "test-model",
        "test-key",
        transport=httpx.MockTransport(respond),
        retry_delay=0,
    )
    with pytest.raises(AppError):
        await client.complete([{"role": "user", "content": "test"}], [])
    assert len(calls) == attempts
    await client.close()


async def test_T10_transport_timeout_retried_twice():
    calls = []

    async def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout")

    client = QwenClient(
        "http://test", "model", "key", transport=httpx.MockTransport(respond), retry_delay=0
    )
    with pytest.raises(AppError) as error:
        await client.complete([], [])
    assert error.value.code == "model_unavailable"
    assert len(calls) == 3
    await client.close()
