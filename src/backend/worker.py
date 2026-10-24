"""Worker of the stages: claims Procrastinate jobs; several workers may run side by side."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from procrastinate import App

from .config import Settings
from .container import Container
from .infrastructure.queue import STAGE1_QUEUE, STAGE2_QUEUE, STEER_QUEUE
from .tasks import register

logger = logging.getLogger(__name__)
STALLED_CHECK_SECONDS = 30
# Work handed from one stage to the next shares the job lock, so it is fetched by polling
# once the previous task ends; the library default of five seconds would show as a pause.
FETCH_SECONDS = 1


async def retry_stalled(queue: App) -> int:
    """Jobs of a worker that died without a heartbeat go back to the queue."""
    retried = 0
    for job in await queue.job_manager.get_stalled_jobs():
        logger.warning("Retrying stalled job %s", job.id)
        try:
            await queue.job_manager.retry_job(job)
            retried += 1
        except Exception:
            # Another worker may have returned it to the queue first.
            logger.info("Stalled job %s was already retried", job.id)
    return retried


async def recover_stalled(queue: App, interval: float = STALLED_CHECK_SECONDS) -> None:
    """Checking only at startup misses the job killed by that same restart.

    The dead worker's last heartbeat is still fresh then, so the check runs as long as the
    worker does.
    """
    while True:
        try:
            await retry_stalled(queue)
        except Exception:
            logger.exception("Stalled job check failed")
        await asyncio.sleep(interval)


async def main() -> None:
    settings = Settings()
    container = Container(settings)
    register(container)
    try:
        async with container.queue.open_async():
            recovery = asyncio.create_task(recover_stalled(container.queue))
            try:
                # Every queue whose tasks hold the job lock is served here, or a waiting task
                # of one queue would hold back the job's work in the others. Deliveries the
                # user sends at once run beside that work under a lock of their own.
                await container.queue.run_worker_async(
                    queues=[STAGE1_QUEUE, STAGE2_QUEUE, STEER_QUEUE],
                    concurrency=settings.worker_concurrency,
                    fetch_job_polling_interval=FETCH_SECONDS,
                )
            finally:
                recovery.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await recovery
    finally:
        await container.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
