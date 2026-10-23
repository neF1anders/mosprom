from uuid import uuid4

import httpx
import pytest

from src.backend.domain.errors import AppError
from src.backend.infrastructure.handoff import HttpHandoff
from tests.handoff_server import app

pytestmark = pytest.mark.unit


async def test_T13_receiver_deduplicates_delivery():
    key = str(uuid4()) + ":1"
    transport = httpx.ASGITransport(app=app)
    sender = HttpHandoff("http://receiver/cards", transport=transport)
    assert await sender.deliver(key, {"revision": 1}) == "delivered"
    assert await sender.deliver(key, {"revision": 1}) == "delivered"
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            "http://receiver/cards",
            headers={"Idempotency-Key": key},
            json={"idempotency_key": key, "card": {"revision": 1}},
        )
    assert response.json()["duplicate"]


@pytest.mark.parametrize(
    "case", ["not_connected", "changed_payload", "server_error", "timeout", "authorization"]
)
async def test_T13_delivery_failure_boundaries(case):
    if case == "not_connected":
        assert await HttpHandoff().deliver("job:1", {}) == "not_connected"
        return
    if case == "changed_payload":
        sender = HttpHandoff("http://receiver/cards", transport=httpx.ASGITransport(app=app))
        key = str(uuid4()) + ":1"
        await sender.deliver(key, {"revision": 1})
        with pytest.raises(AppError, match="передача"):
            await sender.deliver(key, {"revision": 2})
        return

    async def respond(request):
        if case == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(401 if case == "authorization" else 503)

    sender = HttpHandoff("http://receiver/cards", transport=httpx.MockTransport(respond))
    with pytest.raises(AppError) as error:
        await sender.deliver("job:1", {})
    assert error.value.code == "handoff_failed"
