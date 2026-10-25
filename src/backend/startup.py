from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path

from .container import Container
from .domain.models import Knowledge
from .infrastructure.database import create_schema

logger = logging.getLogger(__name__)
PARENT_CHECK_SECONDS = 3


async def import_knowledge(
    container: Container, path: Path = Path("knowledge/catalog.json")
) -> int:
    records = [Knowledge.model_validate(item) for item in json.loads(path.read_text("utf-8"))]
    async with container.uow() as uow:
        for record in records:
            await uow.knowledge.put(record)
        await uow.commit()
    return len(records)


async def prepare(container: Container) -> None:
    container.settings.data_dir.mkdir(parents=True, exist_ok=True)
    await create_schema(container.engine)
    await import_knowledge(container)
    await container.runner.start()


def parent_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        # константы WinAPI
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def exit_with_parent(pid: int) -> None:
    """Выходит вместе с плагином."""
    while parent_alive(pid):
        await asyncio.sleep(PARENT_CHECK_SECONDS)
    logger.warning("Parent process %s is gone, exiting", pid)
    os._exit(0)


def watch_parent(pid: int) -> asyncio.Task[None] | None:
    return asyncio.create_task(exit_with_parent(pid)) if pid else None


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
