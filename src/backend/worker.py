from __future__ import annotations

import asyncio
import logging
import signal
from uuid import uuid4

from .config import Settings
from .container import Container
from .domain.errors import AppError

logger = logging.getLogger(__name__)


async def heartbeat(container, work, task):
    while not task.done():
        await asyncio.sleep(5)
        async with container.uow() as uow:
            valid = await uow.queue.heartbeat(work)
            await uow.commit()
        if not valid:
            task.cancel()
            return


async def execute(container, work):
    task = asyncio.create_task(container.pipeline.run(work))
    pulse = asyncio.create_task(heartbeat(container, work, task))
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Worker operation failed for job %s", work.job_id)
        await container.pipeline._fail(
            work, AppError("Внутренняя ошибка обработки, состояние сохранено", "worker_error", 503)
        )
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    async with container.uow() as uow:
        await uow.queue.finish(work)
        await uow.commit()


async def main():
    container = Container(Settings())
    owner, stop = str(uuid4()), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            async with container.uow() as uow:
                work = await uow.queue.claim(owner)
                await uow.commit()
            if work:
                await execute(container, work)
                continue
            try:
                await asyncio.wait_for(stop.wait(), 0.5)
            except TimeoutError:
                pass
    finally:
        await container.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
