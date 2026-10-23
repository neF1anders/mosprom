import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from src.backend.infrastructure.tables import metadata


def configure(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        await connection.run_sync(configure)
    await engine.dispose()


asyncio.run(run())
