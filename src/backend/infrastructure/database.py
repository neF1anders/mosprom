from __future__ import annotations

import asyncio
from types import TracebackType

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .notifier import Notifier
from .queue import SqlQueue
from .repositories import (
    AttachmentRepository,
    CacheRepository,
    EventRepository,
    JobRepository,
    KnowledgeRepository,
    MessageRepository,
    QueuedRepository,
    ReceiptRepository,
    StageResultRepository,
    TraceRepository,
)
from .tables import metadata

BUSY_TIMEOUT_MS = 30_000


class UnitOfWork:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        notifier: Notifier,
        wake: asyncio.Event,
    ):
        self._factory, self._notifier, self._wake = factory, notifier, wake

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._factory()
        self._session.info["notify"] = set()
        self._session.info["wake"] = False
        self.jobs = JobRepository(self._session)
        self.messages = MessageRepository(self._session)
        self.queued = QueuedRepository(self._session)
        self.attachments = AttachmentRepository(self._session)
        self.receipts = ReceiptRepository(self._session)
        self.cache = CacheRepository(self._session)
        self.events = EventRepository(self._session)
        self.queue = SqlQueue(self._session)
        self.knowledge = KnowledgeRepository(self._session)
        self.traces = TraceRepository(self._session)
        self.stage_results = StageResultRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
        # будим после коммита
        for job_id in self._session.info["notify"]:
            self._notifier.notify(job_id)
        self._session.info["notify"] = set()
        if self._session.info["wake"]:
            self._wake.set()
            self._session.info["wake"] = False


def _configure(engine: AsyncEngine) -> None:
    """Настраивает SQLite для одного пользователя."""

    @event.listens_for(engine.sync_engine, "connect")
    def on_connect(connection, record):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def on_begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def database(url: str, notifier: Notifier, wake: asyncio.Event):
    engine = create_async_engine(url)
    _configure(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, lambda: UnitOfWork(factory, notifier, wake)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
