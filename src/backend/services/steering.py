"""Delivery of the queued messages at a safe point of the work, or at once on the user's send.

The messages are claimed under the job's lock and the agent «Корректировка» decides outside
it. The decision is applied under the lock again, and only while nothing changed meanwhile:
a correction starts a new revision with the messages, a reply leaves the work as it is.
Whatever goes wrong, the messages wait in the queue again.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..agents.steer import Decision, Steer
from ..domain.errors import AppError, OperationCancelled
from ..domain.models import Event, Job, Message, QueuedMessage, Status, identifier, now
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import changed

logger = logging.getLogger(__name__)
# A claim older than this belongs to a delivery that died with its worker.
CLAIM_TIMEOUT = timedelta(seconds=120)
# After this many failed deliveries only the user's own send delivers a message.
MAX_ATTEMPTS = 2
# How long the work waits for the decision at a safe point.
DECIDE_SECONDS = 30
# A job waiting for answers, failed or stopped keeps its queue for the user's next send: a
# delivery would spend the one round of questions or start work nobody asked for.
DELIVERABLE = {Status.QUEUED, Status.RUNNING, Status.COMPLETED}
FILES_CHANGED = "Учитываю новые файлы и разбираю задание заново"
FAILED = "Сообщение пока не доставлено и ждёт в очереди"


@dataclass(frozen=True)
class Claim:
    id: str
    job: Job
    items: list[QueuedMessage]


class Steering:
    def __init__(self, uow: UowFactory, steer: Steer):
        self.uow, self.steer = uow, steer

    async def deliver(self, job_id: str, revision: int | None = None, force: bool = False) -> bool:
        """True when a correction replaced the work with a new revision.

        ``revision`` is the work of the caller's safe point; ``force`` is the user's own send,
        which takes the messages that failed before as well.
        """
        claim = await self._claim(job_id, revision, force)
        if claim is None:
            return False
        try:
            return await self._settle(claim, await self._decide(claim))
        except OperationCancelled:
            # A stop or a new revision came first: the messages wait again or went with it.
            await self._release(claim)
        except TimeoutError:
            await self._release(claim, "steer_timeout")
        except AppError as exc:
            await self._release(claim, exc.code)
        except asyncio.CancelledError:
            await asyncio.shield(self._release(claim))
            raise
        except Exception:
            # The work goes on without the agent; the bug stays visible in the log.
            logger.exception("Delivery of the queue of job %s failed", job_id)
            await self._release(claim, "internal")
        return False

    async def _claim(self, job_id: str, revision: int | None, force: bool) -> Claim | None:
        """An empty queue costs one indexed read; the messages are claimed under the lock."""
        at = now()
        async with self.uow() as uow:
            waiting = await uow.queued.list(job_id)
        if not any(claimable(item, force, at) for item in waiting):
            return None
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id, lock=True)
            items = [item for item in await uow.queued.list(job_id) if claimable(item, force, at)]
            if not items or not _open(job, revision):
                return None
            claim = Claim(identifier(), job, items)
            for item in items:
                item.status, item.claim = "delivering", claim.id
                item.claimed_at = item.updated_at = at
                await uow.queued.save(item)
            await uow.commit()
        return claim

    async def _decide(self, claim: Claim) -> Decision:
        """New files are a correction whatever the text says: stage one reads them anew."""
        if claim.job.files_changed:
            return Decision(True, FILES_CHANGED)
        texts = [item.text for item in claim.items]
        return await asyncio.wait_for(self.steer.decide(claim.job, texts), DECIDE_SECONDS)

    async def _settle(self, claim: Claim, decision: Decision) -> bool:
        """The decision holds while the claim and the revision stand and the job still takes
        deliveries; a stage that only moved on, say from stage one to stage two, keeps it."""
        async with self.uow() as uow:
            job = await uow.jobs.get(claim.job.id, lock=True)
            items = await _claimed(uow, claim)
            if len(items) != len(claim.items) or not _open(job, claim.job.revision):
                await _free(uow, items)
                await uow.commit()
                return False
            if decision.correction:
                await changed(uow, job, "Правка принята", correction=True)
                await _event(uow, job, "steer.applied", decision.text, summary=decision.text)
            else:
                await _reply(uow, job, items, decision.text)
            await uow.commit()
        return decision.correction

    async def _release(self, claim: Claim, failure: str | None = None) -> None:
        """The messages wait again; a failure counts against them and tells the chat."""
        async with self.uow() as uow:
            job = await uow.jobs.get(claim.job.id, lock=True)
            items = await _claimed(uow, claim)
            await _free(uow, items, failure is not None)
            if failure is not None and items:
                await _event(uow, job, "steer.failed", FAILED, code=failure)
            await uow.commit()


def claimable(item: QueuedMessage, force: bool, at: datetime) -> bool:
    """Free to deliver; a message that failed twice goes only with the user's own send."""
    return not busy(item, at) and (force or item.attempts < MAX_ATTEMPTS)


def busy(item: QueuedMessage, at: datetime) -> bool:
    """Claimed by a delivery that is still running."""
    claimed = item.claimed_at
    return item.status == "delivering" and claimed is not None and at - claimed < CLAIM_TIMEOUT


def _open(job: Job, revision: int | None) -> bool:
    """Work in progress or just done, in the revision the delivery was meant for."""
    return not job.deleted and job.status in DELIVERABLE and revision in (None, job.revision)


async def _claimed(uow: UnitOfWork, claim: Claim) -> list[QueuedMessage]:
    return [item for item in await uow.queued.list(claim.job.id) if item.claim == claim.id]


async def _free(uow: UnitOfWork, items: list[QueuedMessage], failed: bool = False) -> None:
    for item in items:
        item.status, item.claim, item.claimed_at, item.updated_at = "queued", None, None, now()
        if failed:
            item.attempts += 1
        await uow.queued.save(item)


async def _reply(uow: UnitOfWork, job: Job, items: list[QueuedMessage], text: str) -> None:
    """The work goes on; the messages and the reply join the chat, which no agent reads."""
    for item in items:
        await uow.messages.add(
            Message(
                job_id=job.id,
                revision=job.revision,
                role="user",
                kind="offtopic",
                text=item.text,
                created_at=item.created_at,
            )
        )
    await uow.messages.add(
        Message(job_id=job.id, revision=job.revision, role="assistant", kind="steer", text=text)
    )
    await uow.queued.remove([item.id for item in items])
    await _event(uow, job, "steer.replied", text)


async def _event(uow: UnitOfWork, job: Job, type: str, message: str, **data: Any) -> None:
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type=type,
            status=job.status,
            message=message,
            data=data,
        )
    )
