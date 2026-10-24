"""Concurrent steps of one run share its fate: the first failure stops the others."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any


async def together(*steps: Awaitable[Any]) -> list[Any]:
    """Runs steps at once; the first failure cancels the rest and is raised as it is."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks: list[asyncio.Task[Any]] = [
                group.create_task(step)  # type: ignore[arg-type]
                for step in steps
            ]
    except BaseExceptionGroup as group_error:
        raise group_error.exceptions[0] from None
    return [task.result() for task in tasks]
