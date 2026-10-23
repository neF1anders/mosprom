from __future__ import annotations

from ..domain.errors import AppError, OperationCancelled
from ..domain.evidence import apply_answers, merge_cards, validate_evidence
from ..domain.models import Geometry, Message, Status, TaskCard, Work
from ..domain.rules import assess, known
from ..domain.task_cards import assemble_card, bind_analysis
from ..ports.operations import Handoff
from ..ports.persistence import UowFactory
from .context import source_batches
from .extraction import ExtractionService
from .geometry import GeometryService
from .preparation import PreparationService
from .runtime import Runtime


class Pipeline:
    def __init__(
        self,
        uow: UowFactory,
        preparation: PreparationService,
        geometry: GeometryService,
        extraction: ExtractionService,
        handoff: Handoff,
    ):
        self.uow, self.preparation, self.geometry = uow, preparation, geometry
        self.extraction, self.handoff = extraction, handoff

    async def run(self, work: Work) -> None:
        runtime = Runtime(self.uow, work)
        try:
            await runtime.check()
            job = await self._start(work)
            attachments = await self.preparation.prepare(job, runtime)
            geometry, stl_analysis = await self._geometry(job, attachments, runtime)
            sources = await self.preparation.sources(job, attachments)
            card = await self._extract(job, attachments, sources, geometry, runtime)
            card = assemble_card(card, job, stl_analysis)
            await runtime.check()
            await self._finish(work, card, attachments)
        except OperationCancelled:
            await self._cancel(work)
        except AppError as exc:
            await self._fail(work, exc)

    async def _start(self, work):
        async with self.uow() as uow:
            job = await uow.jobs.get(work.job_id, lock=True)
            if job.revision != work.revision or job.status in {Status.STOPPING, Status.STOPPED}:
                raise OperationCancelled()
            job.status = Status.RUNNING
            await uow.jobs.save(job)
            await uow.commit()
        return job

    async def _geometry(self, job, attachments, runtime):
        active = next(
            (a for a in attachments if a.id == job.active_stl and a.status == "completed"), None
        )
        if active is None:
            return Geometry(), None
        await runtime.check()
        await runtime.event("geometry.started", "Измеряю габариты и проверяю STL")
        try:
            geometry, report, cached = await self.geometry.analyze(active, job.units)
            stl_analysis = bind_analysis(active, job.units, report)
        except AppError as exc:
            await runtime.event("geometry.failed", exc.message, "failed", code=exc.code)
            return Geometry(limitations=[exc.message]), None
        await self._save_geometry_artifacts(active, geometry)
        await runtime.event(
            "geometry.completed",
            "Геометрия проверена, ограничения сохранены",
            "completed",
            geometry=geometry.model_dump(),
            cached=cached,
        )
        return geometry, stl_analysis

    async def _save_geometry_artifacts(self, attachment, geometry):
        artifacts = list(attachment.artifacts)
        if geometry.report_id:
            artifacts.append(geometry.report_id + ".json")
        if geometry.preview_id:
            artifacts.append(geometry.preview_id)
        attachment.artifacts = list(dict.fromkeys(artifacts))
        async with self.uow() as uow:
            await uow.jobs.attachment(attachment)
            await uow.commit()

    async def _extract(self, job, attachments, sources, geometry, runtime):
        cards = []
        await runtime.event("requirements.started", "Выделяю требования и проверяю источники")
        for batch in source_batches(sources):
            context = {
                "sources": batch,
                "images": await self.preparation.images(batch),
                "answers": job.answers,
                "previous_questions": [q.model_dump() for q in job.card.questions]
                if job.card
                else [],
                "resolutions": job.resolutions,
                "geometry": geometry.model_dump(),
                "active_stl": job.active_stl,
                "units": job.units,
            }
            candidate = await self.extraction.extract(context, job, attachments, runtime)
            cards.append(validate_evidence(candidate, sources))
        card = merge_cards(cards)
        card.revision, card.geometry = job.revision, geometry
        card.source_versions = [{"id": a.id, "sha256": a.sha256} for a in attachments]
        card.source_versions.append({"id": job.id, "revision": str(job.revision)})
        if known(job.answers.get("purpose")):
            card.purpose = job.answers["purpose"]
        apply_answers(card, job.answers, job.resolutions, f"job:{job.id}:answers:{job.revision}")
        failures = [a.filename for a in attachments if a.status == "failed"]
        if failures:
            card.unknowns.append("Не прочитаны вложения " + ", ".join(failures))
        card = assess(card, job.answers)
        if failures:
            card.blocked_actions.setdefault("select_parameters", []).append(
                "Не прочитаны все сопроводительные файлы"
            )
            card.allowed_actions = [a for a in card.allowed_actions if a != "select_parameters"]
            card.readiness = "blocked"
        return card

    async def _finish(self, work, card: TaskCard, attachments):
        async with self.uow() as uow:
            job = await uow.jobs.get(work.job_id, lock=True)
            if job.revision != work.revision or job.status in {Status.STOPPING, Status.STOPPED}:
                raise OperationCancelled()
            if not await uow.queue.heartbeat(work):
                raise OperationCancelled()
            job.card = card
            job.status = Status.WAITING if card.readiness == "blocked" else Status.COMPLETED
            job.error = None
            job.handoff = "not_connected" if job.status == Status.COMPLETED else "not_ready"
            await uow.jobs.save(job)
            await uow.jobs.card_version(job)
            text = (
                "Карточка подготовлена, следующий этап не подключён"
                if job.status == Status.COMPLETED
                else "Проверки завершены, нужны уточнения"
            )
            await uow.jobs.message(
                Message(job_id=job.id, revision=job.revision, role="assistant", text=text)
            )
            from ..domain.models import Event

            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="stage1.completed",
                    status=job.status,
                    message=text,
                )
            )
            await uow.commit()
        if job.status == Status.COMPLETED:
            await self._deliver(work, card)

    async def _deliver(self, work, card):
        await Runtime(self.uow, work).check()
        result = await self.handoff.deliver(
            f"{work.job_id}:{work.revision}", card.model_dump(mode="json")
        )
        async with self.uow() as uow:
            job = await uow.jobs.get(work.job_id, lock=True)
            if job.revision == work.revision and job.status == Status.COMPLETED:
                job.handoff = result
                await uow.jobs.save(job)
                await uow.commit()

    async def _cancel(self, work):
        async with self.uow() as uow:
            job = await uow.jobs.get(work.job_id, lock=True)
            if job.status == Status.STOPPING:
                job.status = Status.STOPPED
                await uow.jobs.save(job)
                await uow.commit()

    async def _fail(self, work, error):
        async with self.uow() as uow:
            job = await uow.jobs.get(work.job_id, lock=True)
            if job.revision != work.revision or not await uow.queue.heartbeat(work):
                return
            if job.status in {Status.STOPPING, Status.STOPPED}:
                job.status = Status.STOPPED
            else:
                job.status, job.error = Status.FAILED, error.message
            await uow.jobs.save(job)
            from ..domain.models import Event

            await uow.events.append(
                Event(
                    job_id=job.id,
                    revision=job.revision,
                    type="operation.failed",
                    status=job.status,
                    message=error.message,
                    data={"code": error.code},
                )
            )
            await uow.commit()
