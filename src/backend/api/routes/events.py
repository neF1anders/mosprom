from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..dependencies import Services, User

router = APIRouter(tags=["events"])


@router.get("/jobs/{job_id}/events")
async def events(
    job_id: str,
    request: Request,
    services: Services,
    user: User,
    after: int = Query(default=0, ge=0),
):
    await services.jobs.ensure_owner(user, job_id)
    last_id = request.headers.get("last-event-id", "")
    cursor = max(after, int(last_id)) if last_id.isdigit() else after

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            batch = await services.jobs.events(job_id, cursor)
            for event in batch:
                cursor = event.event_id
                yield f"id: {cursor}\ndata: {event.model_dump_json()}\n\n"
            if not batch:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
