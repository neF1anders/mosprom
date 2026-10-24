"""Procrastinate jobs are inserted on the caller's transaction, so state and work commit together."""

from __future__ import annotations

from procrastinate import App, PsycopgConnector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STAGE1_TASK = "stage1.run"
STAGE1_QUEUE = "stage1"
# Parameter selection and its check run as this task; its payload is {job_id, revision}.
STAGE2_TASK = "stage2.select_parameters"
STAGE2_QUEUE = "stage2"


def queue_app(database_url: str) -> App:
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return App(connector=PsycopgConnector(conninfo=conninfo))


class ProcrastinateQueue:
    def __init__(self, session: AsyncSession, app: App):
        self._session, self._app = session, app

    async def stage1(self, job_id: str, revision: int) -> None:
        await self._defer(STAGE1_TASK, STAGE1_QUEUE, job_id, revision)

    async def stage2(self, job_id: str, revision: int) -> None:
        await self._defer(STAGE2_TASK, STAGE2_QUEUE, job_id, revision)

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

    async def _defer(self, task: str, queue: str, job_id: str, revision: int) -> None:
        connection = await (await self._session.connection()).get_raw_connection()
        deferrer = self._app.configure_task(
            task, queue=queue, lock=_lock(job_id), connection=connection.driver_connection
        )
        await deferrer.defer_async(job_id=job_id, revision=revision)


def _lock(job_id: str) -> str:
    """One lock per job keeps its work in order across all queues."""
    return f"job:{job_id}"
