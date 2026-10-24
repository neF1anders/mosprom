"""Procrastinate jobs are inserted on the caller's transaction, so state and work commit together."""

from __future__ import annotations

from typing import Any

from procrastinate import App, PsycopgConnector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STAGE1_TASK = "stage1.run"
STAGE1_QUEUE = "stage1"
# Parameter selection and its check run as this task; its payload is {job_id, revision}.
STAGE2_TASK = "stage2.select_parameters"
STAGE2_QUEUE = "stage2"
# Delivers the queued messages the user sends at once, beside the job's work; its payload is
# {job_id}.
STEER_TASK = "steer.deliver"
STEER_QUEUE = "steer"


def queue_app(database_url: str) -> App:
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return App(connector=PsycopgConnector(conninfo=conninfo))


class ProcrastinateQueue:
    def __init__(self, session: AsyncSession, app: App):
        self._session, self._app = session, app

    async def stage1(
        self, job_id: str, revision: int, start: bool = False, correction: bool = False
    ) -> None:
        arguments: dict[str, Any] = {"job_id": job_id, "revision": revision, "start": start}
        if correction:
            # Only a correction carries its flag, so ordinary work keeps the payload it had.
            arguments["correction"] = True
        await self._defer(STAGE1_TASK, STAGE1_QUEUE, _lock(job_id), arguments)

    async def stage2(self, job_id: str, revision: int) -> None:
        arguments = {"job_id": job_id, "revision": revision}
        await self._defer(STAGE2_TASK, STAGE2_QUEUE, _lock(job_id), arguments)

    async def steer(self, job_id: str) -> None:
        """Under the job's lock it would wait for the stage to end; a lock of its own keeps
        one delivery of the job at a time."""
        await self._defer(STEER_TASK, STEER_QUEUE, f"steer:{job_id}", {"job_id": job_id})

    async def cancel_pending(self, job_id: str) -> None:
        """Work queued for an earlier revision is obsolete.

        A waiting job keeps the job lock, and Procrastinate fetches nothing behind it, in any
        queue, so it would hold back the new revision's work.
        """
        await self._session.execute(
            text(
                "SELECT procrastinate_cancel_job_v1(id, false, false) FROM procrastinate_jobs "
                "WHERE lock = :lock AND status = 'todo'"
            ),
            {"lock": _lock(job_id)},
        )

    async def _defer(self, task: str, queue: str, lock: str, arguments: dict[str, Any]) -> None:
        connection = await (await self._session.connection()).get_raw_connection()
        deferrer = self._app.configure_task(
            task, queue=queue, lock=lock, connection=connection.driver_connection
        )
        await deferrer.defer_async(**arguments)


def _lock(job_id: str) -> str:
    """One lock per job keeps its work in order across all queues."""
    return f"job:{job_id}"
