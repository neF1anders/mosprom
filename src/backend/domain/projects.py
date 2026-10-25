from __future__ import annotations

from pathlib import PurePath
from typing import Any

from .models import Attachment, Job, Project


def in_project(attachment: Attachment, job: Job) -> bool:
    """Файл текущего проекта чата."""
    project = job.project
    if project is None:
        return True
    return attachment.project == project.number


def unassigned(job: Job, attachments: list[Attachment], sent: set[str]) -> list[Attachment]:
    """Новые файлы без проекта."""
    files = [a for a in attachments if a.project is None and a.active and not a.draft]
    if job.project is None and job.revision > 0:
        return [a for a in files if a.id in sent]
    return files


def project_messages(job: Job, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сообщения текущего проекта чата."""
    project = job.project
    if project is None:
        return messages
    return [m for m in messages if m.get("seq", 0) >= project.first_message]


def first_message(job: Job, messages: list[dict[str, Any]], pending: list[dict[str, Any]]) -> int:
    """Начало сообщений нового проекта."""
    first = pending[0]["seq"] if pending else 0
    since = job.project.first_message if job.project else 0
    requests = [m["seq"] for m in messages if m.get("kind") == "gate" and since <= m["seq"] < first]
    if not requests:
        return first
    users = [m["seq"] for m in messages if m["role"] == "user" and since <= m["seq"] < requests[-1]]
    return users[-1] if users else requests[-1]


def start_project(job: Job, title: str, notes: str, first_message: int) -> Project:
    """Начало следующей части чата."""
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
    """Новые файлы в текущий проект."""
    project = job.project
    for attachment in files:
        attachment.project = project.number if project else None
    return files


def earlier_answers(job: Job) -> dict[str, str]:
    """Ответы пользователя из прошлых частей."""
    answers: dict[str, str] = {}
    for project in job.projects[:-1]:
        answers.update(project.answers)
    return answers


def part_name(job: Job) -> str:
    """Название папки готового проекта."""
    if job.project is not None:
        return job.project.title
    files = job.card.files if job.card else []
    models = [f.filename for f in files if f.filename.lower().endswith(".stl")]
    return PurePath(models[0]).stem if models else job.title
