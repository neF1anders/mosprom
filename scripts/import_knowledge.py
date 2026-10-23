import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend.config import Settings
from src.backend.domain.models import Knowledge
from src.backend.infrastructure.database import database
from src.backend.infrastructure.queue import queue_app


async def main():
    records = [
        Knowledge.model_validate(item)
        for item in json.loads(Path("knowledge/catalog.json").read_text())
    ]
    url = Settings().database_url
    engine, factory = database(url, queue_app(url))
    try:
        async with factory() as uow:
            for record in records:
                await uow.knowledge.put(record)
            await uow.commit()
    finally:
        await engine.dispose()
    print(f"Imported {len(records)} KB-001 records")


if __name__ == "__main__":
    asyncio.run(main())
