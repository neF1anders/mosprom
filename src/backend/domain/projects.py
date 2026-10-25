"""The parts one chat works on: which files and messages belong to the current one.

A chat without projects is the chat of before: every file and message is its one part.
"""

from __future__ import annotations

from typing import Any

from .models import Attachment, Job, Project


def in_project(attachment: Attachment, job: Job) -> bool:
    """A file of the current project; before the first one, every sent file."""
    project = job.project
    if project is None:
        return True
    return attachment.project == project.number


def unassigned(job: Job, attachments: list[Attachment], sent: set[str]) -> list[Attachment]:
    """The new files: sent and not taken by a project yet.

    A chat of before projects counts its earlier files as its work, so only the files of the
    messages decided now, ``sent``, are new there.
    """
    files = [a for a in attachments if a.project is None and a.active and not a.draft]
    if job.project is None and job.revision > 0:
        return [a for a in files if a.id in sent]
    return files


def project_messages(job: Job, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages of the current project; the earlier ones belong to earlier parts."""
    project = job.project
    if project is None:
        return messages
    return [m for m in messages if m.get("seq", 0) >= project.first_message]


def first_message(job: Job, messages: list[dict[str, Any]], pending: list[dict[str, Any]]) -> int:
    """Where a new project's messages begin: at the messages that start it, or earlier, at
    the message the assistant answered with its one request for details."""
    first = pending[0]["seq"] if pending else 0
    since = job.project.first_message if job.project else 0
    requests = [m["seq"] for m in messages if m.get("kind") == "gate" and since <= m["seq"] < first]
    if not requests:
        return first
    users = [m["seq"] for m in messages if m["role"] == "user" and since <= m["seq"] < requests[-1]]
    return users[-1] if users else requests[-1]


def start_project(job: Job, title: str, notes: str, first_message: int) -> Project:
    """The next part of the chat; the finished one keeps its answers to hint the next.

    The card, the answers and the results describe the previous part, so they go.
    """
    previous = job.project
    if previous is not None:
        previous.answers = {a.title: a.value for a in job.answers.values()}
    project = Project(
        number=len(job.projects) + 1,
        title=title.strip()[:80] or f"Проект {len(job.projects) + 1}",
        notes=notes.strip(),
        first_message=first_message,
        revision=job.revision + 1,
    )
    job.projects.append(project)
    job.card = None
    job.answers = {}
    job.active_stl = None
    job.parameters = job.result = job.outcome = None
    job.stage = "understanding"
    return project


def take_files(job: Job, files: list[Attachment]) -> list[Attachment]:
    """The new files go to the current project; the caller saves them."""
    project = job.project
    for attachment in files:
        attachment.project = project.number if project else None
    return files


def earlier_answers(job: Job) -> dict[str, str]:
    """What the user answered in the finished parts of the chat, newest last."""
    answers: dict[str, str] = {}
    for project in job.projects[:-1]:
        answers.update(project.answers)
    return answers
