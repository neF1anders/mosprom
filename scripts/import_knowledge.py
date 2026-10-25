import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend.config import Settings
from src.backend.container import Container
from src.backend.infrastructure.database import create_schema
from src.backend.startup import import_knowledge


async def main():
    container = Container(Settings())
    try:
        container.settings.data_dir.mkdir(parents=True, exist_ok=True)
        await create_schema(container.engine)
        count = await import_knowledge(container)
    finally:
        await container.close()
    print(f"Imported {count} KB-001 records")


if __name__ == "__main__":
    asyncio.run(main())
