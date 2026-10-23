from __future__ import annotations

from ..domain.errors import AppError, RevisionConflict
from ..domain.models import Answer, Event, Job, Message, Status, now
from ..domain.rules import known
from ..domain.units import STL_UNITS
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class AnswerService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def answer(
        self, user_id: str, job_id: str, request_id: str, revision: int, answers: dict[str, str]
    ):
        async def apply(uow: UnitOfWork, job: Job):
            if job.revision != revision:
                raise RevisionConflict()
            if job.card is None or job.card.revision != job.revision:
                raise AppError("Вопросов для ответа нет", "no_questions", 409)
            questions = {q.id: q for q in job.card.questions}
            if not set(answers).issubset(questions):
                raise AppError("Вопрос больше не актуален", "unknown_question", 409)
            units = answers.get("units", "")
            if known(units) and units not in STL_UNITS:
                raise AppError("Выберите mm, cm, m или inch")
            if known(units):
                job.units = units
            for key, value in answers.items():
                job.answers[key] = Answer(
                    title=questions[key].title, value=value.strip(), revision=revision
                )
            if job.status == Status.RUNNING and job.phase == "deep":
                await joined(uow, job, answers)
            else:
                await changed(uow, job, "Ответы сохранены")
            text = "\n".join(f"{questions[k].title}, {v.strip()}" for k, v in answers.items())
            await uow.jobs.message(
                Message(
                    job_id=job.id, revision=job.revision, role="user", kind="answers", text=text
                )
            )
            return job.model_dump(mode="json")

        payload = {"answers": answers, "revision": revision}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)


async def joined(uow: UnitOfWork, job: Job, answers: dict[str, str]) -> None:
    """The running reading never sees answers; its consolidation reads them, no restart."""
    assert job.card is not None
    for question in job.card.questions:
        if question.id in answers:
            question.answer = answers[question.id].strip()
    job.updated_at = now()
    await uow.jobs.save(job)
    await uow.events.append(
        Event(
            job_id=job.id,
            revision=job.revision,
            type="answers.accepted",
            status=job.status,
            message="Ответы приняты, учту их в сводке",
        )
    )
