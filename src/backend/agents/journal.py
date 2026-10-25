from __future__ import annotations

from typing import Any

from ..domain.models import Job, Requirement
from ..ports.persistence import UowFactory

# кусок рассуждения агента
REASONING_CHARS = 6000
SETTINGS = 30
PROVENANCE = {
    "user": "из сообщения или ответа пользователя",
    "document": "из документа",
    "knowledge": "из базы материалов",
    "assumption": "допущение",
}
MODES = {"classic": "3D", "cylindrical": "5D Spiral", "cylindrical_full": "5D"}


class Journal:
    def __init__(self, uow: UowFactory):
        self.uow = uow

    async def facts(self, job: Job) -> dict[str, Any]:
        """Текущий проект в виде фактов."""
        async with self.uow() as uow:
            revision = job.work_revision
            selected = await uow.stage_results.latest(job.id, revision, "parameters")
            checked = await uow.stage_results.latest(job.id, revision, "validation")
            sliced = await uow.stage_results.latest(job.id, revision, "slicing")
            gcode = await uow.stage_results.latest(job.id, revision, "gcode")
        project = job.project
        facts: dict[str, Any] = {
            "project": {"number": project.number, "title": project.title} if project else None,
            "status": job.status.value,
            "stage": job.stage,
            "outcome": job.outcome,
            "error": job.error,
            **_card(job),
            "parameters": _parameters(selected, job) if selected else None,
            "parameter_check": _check(checked) if checked else None,
            "slicing": _slicing(sliced, job) if sliced else None,
            "gcode_check": _gcode(gcode) if gcode else None,
        }
        return {key: value for key, value in facts.items() if value not in (None, [], {}, "")}

    async def reasoning(self, job: Job) -> str:
        """Сохранённые рассуждения агентов текущей работы."""
        async with self.uow() as uow:
            calls = await uow.traces.calls(job.id, job.work_revision)
        parts = []
        for call in calls:
            message = ((call.response or {}).get("choices") or [{}])[0].get("message") or {}
            text = (message.get("reasoning_content") or "").strip()
            if text:
                parts.append(f"<{call.agent} step={call.step}>\n{text[-REASONING_CHARS:]}\n")
        return "\n".join(parts)


def _card(job: Job) -> dict[str, Any]:
    card = job.card
    if card is None:
        return {}
    answers = {key: answer.value for key, answer in job.answers.items()}
    geometry = card.geometry
    return {
        "files": [f.filename for f in card.files],
        "purpose": card.purpose,
        "requirements": [_requirement(r) for r in card.requirements],
        "assumptions": [{"text": a.text, "basis": a.basis} for a in card.assumptions],
        "unknowns": card.unknowns,
        "questions": [
            {"question": q.title, "answer": answers.get(q.id) or q.answer or "без ответа"}
            for q in card.questions
        ],
        "waived_questions": [{"question": w.title, "reason": w.reason} for w in card.waived],
        "geometry": {
            "extents_mm": geometry.extents,
            "units": geometry.units,
            "defects": geometry.defects,
            "volume_mm3": geometry.volume,
        }
        if geometry
        else None,
    }


def _requirement(requirement: Requirement) -> str:
    value = " ".join(part for part in (requirement.value, requirement.unit) if part)
    conditions = f", {requirement.conditions}" if requirement.conditions else ""
    origin = PROVENANCE.get(requirement.provenance, requirement.provenance)
    return f"{requirement.label or requirement.key} {value}{conditions} ({origin})"


def _parameters(selected: dict[str, Any], job: Job) -> dict[str, Any]:
    mode = selected.get("printing_mode") or {}
    quality = selected.get("quality") or {}
    layer = (selected.get("settings") or {}).get("layer_height") or {}
    settings = list((selected.get("settings") or {}).items())[:SETTINGS]
    return {
        "mode": MODES.get(str(mode.get("value")), mode.get("value")),
        "mode_why": mode.get("why"),
        "quality": _quality(quality.get("quality_type"), job),
        "quality_why": quality.get("why"),
        "layer_height_mm": layer.get("value"),
        "materials": [
            {"id": m.get("id"), "why": m.get("why")}
            for m in (selected.get("materials") or {}).values()
        ],
        "settings": [
            {
                "key": key,
                "value": setting.get("value"),
                "unit": setting.get("unit"),
                "why": setting.get("why"),
            }
            for key, setting in settings
        ],
        "assumptions": [a.get("text") for a in selected.get("assumptions") or []],
        "unsatisfied": [u.get("why") for u in selected.get("unsatisfied") or []],
        "warnings": selected.get("warnings") or [],
        "status": selected.get("status"),
    }


def _quality(code: Any, job: Job) -> Any:
    """Название профиля как в слайсере."""
    name = job.parameters.quality_type if job.parameters else None
    return f"{name} ({code})" if name and code and name != code else code


def _check(checked: dict[str, Any]) -> dict[str, Any]:
    return {
        "result": (checked.get("feedback") or {}).get("result"),
        "issues": [i.get("message") for i in checked.get("issues") or []],
    }


def _slicing(sliced: dict[str, Any], job: Job) -> dict[str, Any]:
    result = job.result
    return {
        "status": sliced.get("status"),
        "message": sliced.get("message"),
        "folder": result.folder if result else None,
        "print_time_seconds": result.print_time_seconds if result else None,
        "material_meters": result.material_meters if result else None,
        "material_grams": result.material_grams if result else None,
        "warnings": sliced.get("warnings") or [],
    }


def _gcode(gcode: dict[str, Any]) -> dict[str, Any]:
    return {
        "result": gcode.get("result"),
        "findings": [f.get("message") for f in gcode.get("findings") or []],
    }
