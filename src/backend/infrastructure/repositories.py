"""One repository per table; the unit of work shares a session between them."""

from __future__ import annotations

import builtins
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import AppError, NotFound
from ..domain.models import (
    AgentCall,
    Attachment,
    Event,
    Job,
    JobHead,
    Knowledge,
    Message,
    QueuedMessage,
)
from ..domain.pipeline import Step
from . import tables as t

EVENTS_CHANNEL = "job_events"


class Repository:
    def __init__(self, session: AsyncSession):
        self._session = session


class JobRepository(Repository):
    async def head(self, job_id: str) -> JobHead:
        row = (
            (
                await self._session.execute(
                    select(
                        t.jobs.c.id,
                        t.jobs.c.payload["revision"].as_integer().label("revision"),
                        t.jobs.c.payload["status"].astext.label("status"),
                    ).where(t.jobs.c.id == job_id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound()
        return JobHead.model_validate(dict(row))

    async def get(self, job_id: str, *, user_id: str | None = None, lock: bool = False) -> Job:
        """Without user_id the caller is the system worker; requests always pass their user."""
        query = select(t.jobs.c.payload).where(t.jobs.c.id == job_id)
        if user_id is not None:
            query = query.where(t.jobs.c.user_id == user_id)
        if lock:
            query = query.with_for_update()
        value = await self._session.scalar(query)
        if value is None:
            raise NotFound()
        job = Job.model_validate(value)
        # A deleted chat is gone for its user; the worker still sees it to stop the run.
        if user_id is not None and job.deleted:
            raise NotFound()
        return job

    async def save(self, job: Job) -> None:
        payload = job.model_dump(mode="json")
        query = insert(t.jobs).values(id=job.id, user_id=job.user_id, payload=payload)
        await self._session.execute(
            query.on_conflict_do_update(
                index_elements=["id"], set_={"payload": query.excluded.payload}
            )
        )

    async def list(
        self, user_id: str, before: str | None = None, limit: int = 50
    ) -> builtins.list[Job]:
        updated = t.jobs.c.payload["updated_at"].astext
        query = (
            select(t.jobs.c.payload.op("-")("card"))
            .where(
                t.jobs.c.user_id == user_id,
                t.jobs.c.payload["deleted"].astext.is_distinct_from("true"),
            )
            .order_by(updated.desc(), t.jobs.c.id.desc())
            .limit(limit)
        )
        if before:
            cursor = select(updated).where(t.jobs.c.id == before).scalar_subquery()
            query = query.where(
                or_(updated < cursor, and_(updated == cursor, t.jobs.c.id < before))
            )
        return [Job.model_validate(v) for v in await self._session.scalars(query)]


class MessageRepository(Repository):
    async def add(self, message: Message) -> int:
        """The message's place in the chat, which a project counts its messages from."""
        return (
            await self._session.execute(
                insert(t.messages)
                .values(job_id=message.job_id, payload=message.model_dump(mode="json"))
                .returning(t.messages.c.seq)
            )
        ).scalar_one()

    async def list(
        self, job_id: str, before: int | None = None, limit: int = 100
    ) -> builtins.list[dict[str, Any]]:
        query = (
            select(t.messages)
            .where(t.messages.c.job_id == job_id)
            .order_by(t.messages.c.seq.desc())
            .limit(limit)
        )
        if before is not None:
            query = query.where(t.messages.c.seq < before)
        rows = (await self._session.execute(query)).mappings()
        return list(reversed([dict(row["payload"], seq=row["seq"]) for row in rows]))


class QueuedRepository(Repository):
    """Messages typed while the job works, in the order they were sent."""

    async def save(self, item: QueuedMessage) -> None:
        query = insert(t.queued_messages).values(
            id=item.id, job_id=item.job_id, payload=item.model_dump(mode="json")
        )
        await self._session.execute(
            query.on_conflict_do_update(
                index_elements=["id"], set_={"payload": query.excluded.payload}
            )
        )

    async def list(self, job_id: str) -> builtins.list[QueuedMessage]:
        rows = await self._session.scalars(
            select(t.queued_messages.c.payload)
            .where(t.queued_messages.c.job_id == job_id)
            .order_by(t.queued_messages.c.seq)
        )
        return [QueuedMessage.model_validate(row) for row in rows]

    async def remove(self, ids: builtins.list[str]) -> None:
        await self._session.execute(
            delete(t.queued_messages).where(t.queued_messages.c.id.in_(ids))
        )


class AttachmentRepository(Repository):
    async def save(self, attachment: Attachment) -> None:
        query = insert(t.attachments).values(
            id=attachment.id, job_id=attachment.job_id, payload=attachment.model_dump(mode="json")
        )
        await self._session.execute(
            query.on_conflict_do_update(
                index_elements=["id"], set_={"payload": query.excluded.payload}
            )
        )

    async def list(self, job_id: str) -> builtins.list[Attachment]:
        rows = await self._session.scalars(
            select(t.attachments.c.payload)
            .where(t.attachments.c.job_id == job_id)
            .order_by(t.attachments.c.id)
        )
        return [Attachment.model_validate(row) for row in rows]


class ReceiptRepository(Repository):
    async def find(self, key: str, payload_hash: str) -> dict[str, Any] | None:
        # Transaction advisory lock also serializes create commands before a job exists.
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )
        row = (
            (await self._session.execute(select(t.receipts).where(t.receipts.c.key == key)))
            .mappings()
            .first()
        )
        if row is None:
            return None
        if row["hash"] != payload_hash:
            raise AppError(
                "Повторный request_id содержит другую команду", "idempotency_conflict", 409
            )
        return row["result"]

    async def remember(self, key: str, payload_hash: str, result: dict[str, Any]) -> None:
        await self._session.execute(
            insert(t.receipts).values(key=key, hash=payload_hash, result=result)
        )


class CacheRepository(Repository):
    async def get(self, key: str) -> dict[str, Any] | None:
        return await self._session.scalar(select(t.cache.c.payload).where(t.cache.c.key == key))

    async def put(self, key: str, value: dict[str, Any]) -> None:
        await self._session.execute(
            insert(t.cache).values(key=key, payload=value).on_conflict_do_nothing()
        )


class EventRepository(Repository):
    async def append(self, event: Event) -> None:
        # Serialize event allocation per job so SSE cursors follow commit order.
        await self._session.execute(
            select(t.jobs.c.id).where(t.jobs.c.id == event.job_id).with_for_update()
        )
        await self._session.execute(
            insert(t.events).values(job_id=event.job_id, payload=event.model_dump(mode="json"))
        )
        # Delivered on commit: open event streams of the job fetch at once instead of polling.
        await self._session.execute(select(func.pg_notify(EVENTS_CHANNEL, event.job_id)))

    async def list(self, job_id: str, after: int = 0, limit: int = 100) -> builtins.list[Event]:
        query = (
            select(t.events)
            .where(t.events.c.job_id == job_id, t.events.c.seq > after)
            .order_by(t.events.c.seq)
            .limit(limit)
        )
        rows = (await self._session.execute(query)).mappings()
        return [Event.model_validate(dict(row["payload"], event_id=row["seq"])) for row in rows]

    async def start(self, job_id: str, revision: int) -> int:
        """The cursor just before the first event of a revision; older history is not replayed."""
        first = await self._session.scalar(
            select(func.min(t.events.c.seq)).where(
                t.events.c.job_id == job_id,
                t.events.c.payload["revision"].as_integer() >= revision,
            )
        )
        if first is not None:
            return first - 1
        latest = await self._session.scalar(
            select(func.max(t.events.c.seq)).where(t.events.c.job_id == job_id)
        )
        return latest or 0


class KnowledgeRepository(Repository):
    async def put(self, record: Knowledge) -> None:
        query = insert(t.knowledge).values(
            id=record.id,
            material_id=record.material_id,
            property=record.property,
            aliases=[a.casefold() for a in record.aliases],
            search=func.to_tsvector("russian", record.text + " " + record.property),
            payload=record.model_dump(mode="json"),
        )
        await self._session.execute(
            query.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    c: query.excluded[c]
                    for c in ["material_id", "property", "aliases", "search", "payload"]
                },
            )
        )

    async def all(self) -> builtins.list[Knowledge]:
        statement = select(t.knowledge.c.payload).order_by(t.knowledge.c.id)
        return [Knowledge.model_validate(v) for v in await self._session.scalars(statement)]


class TraceRepository(Repository):
    async def record(self, call: AgentCall) -> None:
        await self._session.execute(insert(t.agent_calls).values(**call.model_dump()))

    async def calls(self, job_id: str, revision: int) -> builtins.list[AgentCall]:
        """The calls of one revision's work in order, for questions about how it went."""
        rows = await self._session.execute(
            select(t.agent_calls)
            .where(t.agent_calls.c.job_id == job_id, t.agent_calls.c.revision == revision)
            .order_by(t.agent_calls.c.id)
        )
        return [
            AgentCall.model_validate({k: v for k, v in row.items() if k != "id"})
            for row in rows.mappings()
        ]

    async def usage(self, job_id: str) -> tuple[int, int]:
        """Provider calls a job made and the tokens they spent; cached results cost nothing."""
        tokens = t.agent_calls.c.response["usage"]["total_tokens"].as_integer()
        row = (
            await self._session.execute(
                select(func.count(), func.coalesce(func.sum(tokens), 0)).where(
                    t.agent_calls.c.job_id == job_id, ~t.agent_calls.c.cached
                )
            )
        ).one()
        return row[0], row[1]


class StageResultRepository(Repository):
    """Results of the deterministic steps, one per job revision, step and pass."""

    async def add(self, job_id: str, revision: int, step: Step, payload: dict[str, Any]) -> None:
        # A redelivered task writes the same result again; the first one stays.
        await self._session.execute(
            insert(t.stage_results)
            .values(
                job_id=job_id,
                revision=revision,
                stage=step.stage,
                iteration=step.iteration,
                payload=payload,
            )
            .on_conflict_do_nothing()
        )

    async def get(self, job_id: str, revision: int, step: Step) -> dict[str, Any] | None:
        return await self._session.scalar(
            select(t.stage_results.c.payload).where(
                t.stage_results.c.job_id == job_id,
                t.stage_results.c.revision == revision,
                t.stage_results.c.stage == step.stage,
                t.stage_results.c.iteration == step.iteration,
            )
        )

    async def latest(self, job_id: str, revision: int, stage: str) -> dict[str, Any] | None:
        """The last pass of a step in this revision."""
        return await self._session.scalar(
            select(t.stage_results.c.payload)
            .where(
                t.stage_results.c.job_id == job_id,
                t.stage_results.c.revision == revision,
                t.stage_results.c.stage == stage,
            )
            .order_by(t.stage_results.c.iteration.desc())
            .limit(1)
        )
