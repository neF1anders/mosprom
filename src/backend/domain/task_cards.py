"""Server-owned measurement binding and stage-one transport assembly."""

from typing import Any

from .errors import AppError
from .models import CARD_SCHEMA_VERSION, Attachment, Job, StlAnalysis, TaskCard


def bind_analysis(attachment: Attachment, units: str, report: dict[str, Any]) -> StlAnalysis:
    file = report.get("file", {})
    measured_units = report.get("units", {})
    if not isinstance(file, dict) or not isinstance(measured_units, dict):
        raise AppError("Некорректные метаданные отчёта STL", "stale_analysis", 503)
    if file.get("sha256") != attachment.sha256 or measured_units.get("input_unit") != units:
        raise AppError(
            "Отчёт STL не соответствует активному файлу или единицам измерения",
            "stale_analysis",
            503,
        )
    return StlAnalysis(attachment_id=attachment.id, sha256=attachment.sha256, report=report)


def assemble_card(card: TaskCard, job: Job, analysis: StlAnalysis | None) -> TaskCard:
    if analysis is not None and analysis.attachment_id != job.active_stl:
        raise AppError("Изменился активный STL", "stale_analysis", 409)
    return card.model_copy(
        deep=True,
        update={
            "schema_version": CARD_SCHEMA_VERSION,
            "revision": job.revision,
            "stl_analysis": analysis,
            "answers": dict(job.answers),
            "resolutions": dict(job.resolutions),
        },
    )
