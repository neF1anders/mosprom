from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .queue_repository import QueueRepository
from .repositories import EventRepository, JobRepository, KnowledgeRepository


class PostgresUnitOfWork:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self._factory = factory

    async def __aenter__(self) -> "PostgresUnitOfWork":
        self._session = self._factory()
        self.jobs = JobRepository(self._session)
        self.events = EventRepository(self._session)
        self.queue = QueueRepository(self._session)
        self.knowledge = KnowledgeRepository(self._session)
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


def database(url: str):
    engine = create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, lambda: PostgresUnitOfWork(factory)
