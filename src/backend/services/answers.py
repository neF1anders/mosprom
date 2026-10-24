from __future__ import annotations

from ..domain.errors import AppError, RevisionConflict
from ..domain.models import Answer, Job, Message
from ..domain.rules import canonical
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
            # Every way of saying "unknown" is stored as one value the interface recognises.
            values = {key: canonical(value) for key, value in answers.items()}
            for key, value in values.items():
                job.answers[key] = Answer(
                    title=questions[key].title, value=value, revision=revision
                )
            # The answers go back to the checker that asked, in a new revision.
            await changed(uow, job, "Ответы сохранены")
            text = "\n".join(f"{questions[k].title}, {v}" for k, v in values.items())
            await uow.messages.add(
                Message(
                    job_id=job.id, revision=job.revision, role="user", kind="answers", text=text
                )
            )
            return job.model_dump(mode="json")

        payload = {"answers": answers, "revision": revision}
        return await self.commands.execute(user_id, job_id, request_id, payload, apply)
