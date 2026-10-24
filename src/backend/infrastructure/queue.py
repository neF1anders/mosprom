"""Procrastinate jobs are inserted on the caller's transaction, so state and work commit together."""

from __future__ import annotations

from procrastinate import App, PsycopgConnector
from sqlalchemy.ext.asyncio import AsyncSession

STAGE1_TASK = "stage1.run"
STAGE1_QUEUE = "stage1"
# Stage two registers a handler with this name; its payload is {job_id, revision}.
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

    async def _defer(self, task: str, queue: str, job_id: str, revision: int) -> None:
        connection = await (await self._session.connection()).get_raw_connection()
        deferrer = self._app.configure_task(
            task, queue=queue, lock=f"job:{job_id}", connection=connection.driver_connection
        )
        await deferrer.defer_async(job_id=job_id, revision=revision)
