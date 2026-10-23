from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Job, Work, identifier, now
from .tables import queue


class QueueRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def enqueue(self, job: Job) -> None:
        query = insert(queue).values(
            id=identifier(), job_id=job.id, revision=job.revision, status="pending"
        )
        await self._session.execute(
            query.on_conflict_do_update(
                constraint="uq_work_revision",
                set_={"status": "pending", "owner": "", "lease_until": None},
            )
        )

    async def claim(self, owner: str, lease_seconds: int = 30) -> Work | None:
        eligible = or_(
            queue.c.status == "pending",
            and_(queue.c.status == "running", queue.c.lease_until < now()),
        )
        row = (
            (
                await self._session.execute(
                    select(queue)
                    .where(eligible)
                    .order_by(queue.c.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        await self._session.execute(
            update(queue)
            .where(queue.c.id == row["id"])
            .values(
                status="running",
                owner=owner,
                attempts=row["attempts"] + 1,
                lease_until=now() + timedelta(seconds=lease_seconds),
            )
        )
        return Work(
            id=row["id"],
            job_id=row["job_id"],
            revision=row["revision"],
            owner=owner,
            attempts=row["attempts"] + 1,
        )

    async def heartbeat(self, work: Work, lease_seconds: int = 30) -> bool:
        query = (
            update(queue)
            .where(queue.c.id == work.id, queue.c.owner == work.owner, queue.c.status == "running")
            .values(lease_until=now() + timedelta(seconds=lease_seconds))
            .returning(queue.c.id)
        )
        return (await self._session.scalar(query)) is not None

    async def finish(self, work: Work) -> None:
        await self._session.execute(
            update(queue)
            .where(queue.c.id == work.id, queue.c.owner == work.owner)
            .values(status="done", lease_until=None)
        )
