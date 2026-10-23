from __future__ import annotations

from ..domain.errors import AppError, RevisionConflict
from ..domain.models import Job, Message
from ..domain.rules import UNITS, known
from ..ports.persistence import UnitOfWork
from .commands import Commands, changed


class AnswerService:
    def __init__(self, commands: Commands):
        self.commands = commands

    async def answer(
        self,
        job_id: str,
        request_id: str,
        revision: int,
        answers: dict[str, str],
        *,
        conflict: bool = False,
    ):
        async def apply(uow: UnitOfWork, job: Job):
            if job.revision != revision:
                raise RevisionConflict()
            if job.card is None:
                raise AppError("Нет вопросов для ответа")
            items = job.card.conflicts if conflict else job.card.questions
            allowed = {item.id for item in items}
            if not set(answers).issubset(allowed):
                raise AppError("Вопрос больше не актуален", "unknown_question", 409)
            if "geometry.units" in answers and known(answers["geometry.units"]):
                if answers["geometry.units"] not in UNITS:
                    raise AppError("Выберите mm, cm, m или inch")
                job.units = answers["geometry.units"]
            target = job.resolutions if conflict else job.answers
            target.update(answers)
            await changed(uow, job, "Ответы сохранены")
            text = "\n".join(f"{key} = {value}" for key, value in answers.items())
            await uow.jobs.message(
                Message(job_id=job.id, revision=job.revision, role="user", text=text)
            )
            return job.model_dump(mode="json")

        return await self.commands.execute(
            job_id,
            request_id,
            {"answers": answers, "revision": revision, "conflict": conflict},
            apply,
        )
