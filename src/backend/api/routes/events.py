from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...domain.models import Event
from ..dependencies import Services, User

router = APIRouter(tags=["events"])


@router.get("/jobs/{job_id}/events")
async def events(
    job_id: str,
    request: Request,
    services: Services,
    user: User,
    after: int | None = Query(default=None, ge=0),
):
    last_id = request.headers.get("last-event-id", "")
    cursor = max(after or 0, int(last_id)) if last_id.isdigit() else after
    stream = await services.jobs.follow(user, job_id, cursor)
    return StreamingResponse(
        _sse(stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse(stream: AsyncIterator[Event | None]) -> AsyncIterator[str]:
    async for event in stream:
        if event is None:
            yield ": heartbeat\n\n"
        else:
            yield f"id: {event.event_id}\ndata: {event.model_dump_json()}\n\n"
