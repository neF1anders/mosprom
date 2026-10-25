"""Every user message reaches the assistant: at once when the job is idle, at a safe point of
the work when it runs, or at once again on «Скорректировать».

Messages typed during the work are claimed under the job's lock and the assistant decides
outside it. The decision is applied under the lock again, and only while nothing changed
meanwhile: a new project or an update starts a new revision with the messages, a reply
leaves the work as it is. Whatever goes wrong, the messages wait in the queue again.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..agents.assistant import Assistant, Decision, Situation
from ..domain.errors import AppError, OperationCancelled
from ..domain.models import Event, Job, Message, QueuedMessage, Status, identifier, now
from ..domain.projects import first_message, start_project, take_files, unassigned
from ..ports.persistence import UnitOfWork, UowFactory
from .commands import changed

logger = logging.getLogger(__name__)
# A claim older than this belongs to a delivery that died with its worker.
CLAIM_TIMEOUT = timedelta(seconds=120)
# After this many failed deliveries only the user's own send delivers a message.
MAX_ATTEMPTS = 2
# How long the work waits for the decision at a safe point, and a chat turn at most.
DECIDE_SECONDS = 30
ANSWER_SECONDS = 180
# A safe point delivers while the work goes on, waits for answers or has just ended; the
# user's own send delivers whatever the job's state, except a deleted chat.
DELIVERABLE = {Status.QUEUED, Status.RUNNING, Status.WAITING, Status.COMPLETED}
WORKING = {Status.QUEUED, Status.RUNNING}
FAILED = "Сообщение пока не доставлено и ждёт в очереди"
NO_ANSWER = "Не получилось ответить, модель не отвечает. Напишите ещё раз чуть позже"
APPLIED = "Учитываю правку и разбираю задание заново"
STARTED = "Начинаю новый проект"
LATE = "Пока я думал, задание изменилось, напишите ещё раз, если нужно"
PAGE = 100


@dataclass(frozen=True)
class Claim:
    id: str
    job: Job
    items: list[QueuedMessage]


class Steering:
    def __init__(self, uow: UowFactory, assistant: Assistant):
        self.uow, self.assistant = uow, assistant

    async def deliver(self, job_id: str, revision: int | None = None, force: bool = False) -> bool:
        """True when the messages replaced the work with a new revision.

        ``revision`` is the work of the caller's safe point; ``force`` is the user's own send,
        which takes the messages that failed before as well and answers the chat when the
        queue is empty.
        """
        claim = await self._claim(job_id, revision, force)
        replaced = await self._deliver(claim) if claim is not None else False
        # The user's own send also answers what they wrote in the chat meanwhile.
        if force:
            await self.answer(job_id)
        return replaced

    async def answer(self, job_id: str) -> None:
        """The reply to the messages the user sent while the job was idle."""
        job, messages, attachments = await self._read(job_id)
        pending = _pending(messages, job.answered)
        if not pending or job.deleted or job.status in WORKING:
            return
        new = unassigned(job, attachments, _sent(pending))
        situation = Situation(job, messages, attachments, new)

        async def say(text: str, turn: str) -> None:
            await self._say(job, text, turn)

        try:
            decision = await asyncio.wait_for(self.assistant.decide(situation, say), ANSWER_SECONDS)
        except (AppError, TimeoutError) as exc:
            logger.warning("The assistant did not answer in job %s: %r", job_id, exc)
            await self._say(job, NO_ANSWER)
            return
        await self._apply(job, pending, decision, first_message(job, messages, pending))

    async def _deliver(self, claim: Claim) -> bool:
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
            logger.exception("Delivery of the queue of job %s failed", claim.job.id)
            await self._release(claim, "internal")
        return False

    async def _read(self, job_id: str) -> tuple[Job, list[dict[str, Any]], list[Any]]:
        messages: list[dict[str, Any]] = []
        before = None
        async with self.uow() as uow:
            job = await uow.jobs.get(job_id)
            attachments = await uow.attachments.list(job_id)
            while True:
                page = await uow.messages.list(job_id, before, PAGE)
                messages = page + messages
                if len(page) < PAGE:
                    break
                before = page[0]["seq"]
        return job, messages, attachments

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
            if not items or not _open(job, revision, force):
                return None
            claim = Claim(identifier(), job, items)
            for item in items:
                item.status, item.claim = "delivering", claim.id
                item.claimed_at = item.updated_at = at
                await uow.queued.save(item)
            await uow.commit()
        return claim

    async def _decide(self, claim: Claim) -> Decision:
        """During the work nothing is said before the decision: the messages are not in the
        chat yet."""
        _, messages, attachments = await self._read(claim.job.id)
        texts = [item.text for item in claim.items]
        new = unassigned(claim.job, attachments, _sent(item.model_dump() for item in claim.items))
        situation = Situation(claim.job, messages, attachments, new, texts)
        return await asyncio.wait_for(self.assistant.decide(situation, _silent), DECIDE_SECONDS)

    async def _settle(self, claim: Claim, decision: Decision) -> bool:
        """The decision holds while the claim and the revision stand and the job still takes
        deliveries; a stage that only moved on, say from stage one to stage two, keeps it."""
        async with self.uow() as uow:
            job = await uow.jobs.get(claim.job.id, lock=True)
            items = await _claimed(uow, claim)
            if len(items) != len(claim.items) or not _open(job, claim.job.revision, True):
                await _free(uow, items)
                await uow.commit()
                return False
            if decision.action in ("reply", "ask"):
                await _reply(uow, job, items, decision.text)
            else:
                # The new revision takes the claimed messages into the chat before anything.
                sent = _sent(item.model_dump() for item in items)
                await _act(uow, job, decision, [], sent, 0)
            # Every message of the queue went into the chat with this decision.
            await _answered(uow, job, await _last_user_message(uow, job))
            await uow.commit()
        return decision.action not in ("reply", "ask")

    async def _apply(
        self, seen: Job, pending: list[dict[str, Any]], decision: Decision, first: int
    ) -> None:
        """A turn that came too late for a newer revision or a started work only says so."""
        async with self.uow() as uow:
            job = await uow.jobs.get(seen.id, lock=True)
            late = job.revision != seen.revision or job.status in WORKING or job.deleted
            # The messages of this turn are answered; one sent meanwhile waits for its own.
            await _answered(uow, job, pending[-1]["seq"])
            if decision.action in ("reply", "ask"):
                kind = "gate" if decision.action == "ask" else "chat"
                await _say(uow, job, decision.text, kind=kind, turn=decision.turn)
            elif late:
                await _say(uow, job, LATE)
            else:
                await _act(uow, job, decision, pending, _sent(pending), first)
            await uow.commit()

    async def _say(self, job: Job, text: str, turn: str | None = None) -> None:
        async with self.uow() as uow:
            await _say(uow, await uow.jobs.get(job.id), text, turn=turn)
            await uow.commit()

    async def _release(self, claim: Claim, failure: str | None = None) -> None:
        """The messages wait again; a failure counts against them and tells the chat."""
        async with self.uow() as uow:
            job = await uow.jobs.get(claim.job.id, lock=True)
            items = await _claimed(uow, claim)
            await _free(uow, items, failure is not None)
            if failure is not None and items:
                await _event(uow, job, "steer.failed", FAILED, code=failure)
            await uow.commit()


async def _silent(text: str, turn: str) -> None:
    return None


async def _act(
    uow: UnitOfWork,
    job: Job,
    decision: Decision,
    pending: list[dict[str, Any]],
    sent: set[str],
    first: int,
) -> None:
    """A new project takes the files sent since; an update takes them into the current one.

    Typed answers to the open questions continue the checker's dialog; files or a failed or
    stopped run make the work start over; anything else is a correction of the card.
    """
    # The new files are told apart before a new project would take every unassigned one.
    new = unassigned(job, await uow.attachments.list(job.id), sent)
    if decision.action == "start":
        start_project(job, decision.title, decision.notes, first)
    for attachment in take_files(job, new):
        await uow.attachments.save(attachment)
    if decision.text:
        await _say(uow, job, decision.text, event=False, turn=decision.turn)
    if decision.action == "start":
        await _started(uow, job, pending)
        return
    # New files, a file removed with the message or a run that did not end start over.
    fresh = bool(new) or job.files_changed or job.status in (Status.FAILED, Status.STOPPED)
    answering = job.status == Status.WAITING and not fresh
    typed = [m["id"] for m in pending]
    await changed(
        uow, job, "Правка принята", start=fresh, correction=not (fresh or answering), typed=typed
    )
    summary = decision.summary or APPLIED
    await _event(uow, job, "steer.applied", summary, summary=summary)


async def _started(uow: UnitOfWork, job: Job, pending: list[dict[str, Any]]) -> None:
    """Messages typed during the work join the chat with the new revision; the project
    counts its messages from the first of them."""
    first = await changed(uow, job, STARTED, start=True)
    project = job.project
    if project is not None and not pending and first is not None:
        project.first_message = first
        await uow.jobs.save(job)


def claimable(item: QueuedMessage, force: bool, at: datetime) -> bool:
    """Free to deliver; a message that failed twice goes only with the user's own send."""
    return not busy(item, at) and (force or item.attempts < MAX_ATTEMPTS)


def busy(item: QueuedMessage, at: datetime) -> bool:
    """Claimed by a delivery that is still running."""
    claimed = item.claimed_at
    return item.status == "delivering" and claimed is not None and at - claimed < CLAIM_TIMEOUT


def _open(job: Job, revision: int | None, force: bool) -> bool:
    """In the revision the delivery was meant for; a safe point only while the work goes on
    or has just ended."""
    current = revision in (None, job.revision)
    return not job.deleted and current and (force or job.status in DELIVERABLE)


def _sent(messages: Iterable[dict[str, Any]]) -> set[str]:
    """The files the messages were sent with."""
    return {i for m in messages for i in m.get("attachment_ids") or []}


def _pending(messages: list[dict[str, Any]], answered: int) -> list[dict[str, Any]]:
    """The user's chat messages the assistant has not answered yet.

    A message sent while the assistant answered an earlier one stays pending even though
    the reply lands after it; a chat from before the mark counts from its last reply.
    """
    floor = answered or max((m["seq"] for m in messages if m["role"] == "assistant"), default=0)
    return [
        m
        for m in messages
        if m["role"] == "user" and m.get("kind", "chat") == "chat" and m["seq"] > floor
    ]


async def _answered(uow: UnitOfWork, job: Job, seq: int) -> None:
    job.answered = max(job.answered, seq)
    await uow.jobs.save(job)


async def _last_user_message(uow: UnitOfWork, job: Job) -> int:
    recent = await uow.messages.list(job.id, None, PAGE)
    return max((m["seq"] for m in recent if m["role"] == "user"), default=0)


async def _claimed(uow: UnitOfWork, claim: Claim) -> list[QueuedMessage]:
    return [item for item in await uow.queued.list(claim.job.id) if item.claim == claim.id]


async def _free(uow: UnitOfWork, items: list[QueuedMessage], failed: bool = False) -> None:
    for item in items:
        item.status, item.claim, item.claimed_at, item.updated_at = "queued", None, None, now()
        if failed:
            item.attempts += 1
        await uow.queued.save(item)


async def _reply(uow: UnitOfWork, job: Job, items: list[QueuedMessage], text: str) -> None:
    """The work goes on; the messages and the reply join the chat inside the running stage."""
    for item in items:
        await uow.messages.add(
            Message(
                job_id=job.id,
                revision=job.revision,
                role="user",
                kind="offtopic",
                text=item.text,
                attachment_ids=item.attachment_ids,
                created_at=item.created_at,
            )
        )
    await uow.messages.add(
        Message(job_id=job.id, revision=job.revision, role="assistant", kind="steer", text=text)
    )
    await uow.queued.remove([item.id for item in items])
    await _event(uow, job, "steer.replied", text)


async def _say(
    uow: UnitOfWork,
    job: Job,
    text: str,
    event: bool = True,
    kind: str = "chat",
    turn: str | None = None,
) -> None:
    """``kind`` "gate" marks the one request for details; ``turn`` links the reasoning."""
    await uow.messages.add(
        Message(
            job_id=job.id,
            revision=job.revision,
            role="assistant",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            turn=turn,
        )
    )
    if event:
        await _event(uow, job, "assistant.replied", text)


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
