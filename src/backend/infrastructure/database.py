from __future__ import annotations

from types import TracebackType

from procrastinate import App
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .queue import ProcrastinateQueue
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


class PostgresUnitOfWork:
    def __init__(self, factory: async_sessionmaker[AsyncSession], app: App):
        self._factory, self._app = factory, app

    async def __aenter__(self) -> "PostgresUnitOfWork":
        self._session = self._factory()
        self.jobs = JobRepository(self._session)
        self.messages = MessageRepository(self._session)
        self.queued = QueuedRepository(self._session)
        self.attachments = AttachmentRepository(self._session)
        self.receipts = ReceiptRepository(self._session)
        self.cache = CacheRepository(self._session)
        self.events = EventRepository(self._session)
        self.queue = ProcrastinateQueue(self._session, self._app)
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


def database(url: str, app: App):
    engine = create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, lambda: PostgresUnitOfWork(factory, app)
