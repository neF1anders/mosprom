"""Pure assembly of the task card from agent outputs; no I/O, no model calls."""

from __future__ import annotations

import re
from typing import Any

from ..domain.evidence import normalize_text
from ..domain.fields import BY_KEY
from ..domain.hashing import digest
from ..domain.models import Evidence, Question, Requirement, TaskCard
from ..domain.rules import known, purpose_question, units_question
from .runner import RunContext
from .schemas import Draft, DraftQuestion, DraftRequirement, Patch, TriageField

QUOTE_PARTS = re.compile(r"\.{3}|…|(?<=[.!?;])\s+|\n")


def cited(field: TriageField, ctx: RunContext) -> bool:
    """A triage reading counts only with a quote the source really contains.

    A page image vouches for a field only when the page has no text layer to check against.
    """
    source = ctx.sources.get(field.source_id or "")
    if source is None or field.field not in BY_KEY:
        return False
    text = normalize_text(source.text)
    if not text:
        return source.image is not None
    # A quick reading joins sentences from several places; each one must be verbatim.
    parts = [normalize_text(p).rstrip(".") for p in re.split(QUOTE_PARTS, field.quote)]
    parts = [p for p in parts if len(p) >= 3]
    return bool(parts) and all(p in text for p in parts)


def merged(questions: list[Question], answers: dict[str, str]) -> list[Question]:
    """The first question with an id wins; each one carries the user's answer, if any."""
    unique: dict[str, Question] = {}
    for question in questions:
        unique.setdefault(question.id, question)
    for question in unique.values():
        question.answer = answers.get(question.id)
    return list(unique.values())


def first_questions(card: TaskCard, asked: list[Question], answers: dict[str, str]):
    """Questions shown before the deep reading: the STL scale and the triage gaps."""
    scale = [units_question(card.geometry)] if card.geometry is not None else []
    return merged(scale + [q.model_copy() for q in asked], answers)


def card_questions(
    card: TaskCard, drafted: list[DraftQuestion], derived: list[Question], answers: dict[str, str]
) -> list[Question]:
    questions: list[Question] = []
    if card.geometry is not None:
        questions.append(units_question(card.geometry))
    if not card.purpose.strip() or "purpose" in answers:
        questions.append(purpose_question())
    return merged(questions + derived + [to_question(q) for q in drafted], answers)


def numbered(draft: Draft) -> dict[str, Any]:
    """The consolidator edits requirements by these ids, so its answer stays short."""
    view = draft.model_dump()
    view["requirements"] = [
        {"id": f"r{index}", **requirement}
        for index, requirement in enumerate(view["requirements"], 1)
    ]
    return view


def apply_patch(draft: Draft, patch: Patch, questions: list[DraftQuestion]) -> Draft:
    """Applies the consolidator's edit; ids it does not know are ignored."""
    ids = {f"r{index}": r for index, r in enumerate(draft.requirements, 1)}
    removed = {item.id for item in patch.remove}
    changed = {
        item.id: DraftRequirement(**item.model_dump(exclude={"id"}))
        for item in patch.change
        if item.id in ids
    }
    kept = [changed.get(key, r) for key, r in ids.items() if key not in removed]
    return Draft(
        purpose=_patched(draft.purpose, patch.purpose),
        requirements=kept + patch.add,
        preferences=_patched(draft.preferences, patch.preferences),
        production_constraints=_patched(
            draft.production_constraints, patch.production_constraints
        ),
        assumptions=_patched(draft.assumptions, patch.assumptions),
        unknowns=_patched(draft.unknowns, patch.unknowns),
        questions=_patched(unique_questions(questions), patch.questions),
    )


def _patched(current: Any, replacement: Any) -> Any:
    return current if replacement is None else replacement


def unique_questions(questions: list[DraftQuestion]) -> list[DraftQuestion]:
    unique: dict[str, DraftQuestion] = {}
    for question in questions:
        unique.setdefault(question.field or normalize_text(question.title), question)
    return list(unique.values())


def to_question(question: DraftQuestion) -> Question:
    """A question about a triage field keeps the field's id, so its answer is never lost."""
    field = BY_KEY.get(question.field or "")
    return Question(
        id=field.question_id if field else "clarify." + digest(normalize_text(question.title)),
        kind="clarify",
        title=question.title,
        impact=question.impact,
        options=question.options,
        suggested=question.suggested if question.basis else None,
        basis=question.basis,
        blocking=question.blocking,
    )


def to_requirement(draft: DraftRequirement) -> Requirement:
    return Requirement(
        **draft.model_dump(exclude={"sources"}),
        sources=[Evidence(**c.model_dump()) for c in draft.sources],
    )


def discrepancy(item) -> Question:
    anchor = item.requirement_key or normalize_text(item.title)
    return Question(
        id=f"{item.kind}." + digest(anchor),
        kind="discrepancy",
        title=item.title,
        impact=item.impact,
        options=item.options,
        suggested=item.suggested if item.basis else None,
        basis=item.basis,
        sources=[Evidence(**c.model_dump()) for c in item.sources],
        requirement_key=item.requirement_key,
    )


def view(draft: Draft, requirements: list[Requirement], questions: list[Question]) -> dict:
    return {
        "purpose": draft.purpose,
        "requirements": [r.model_dump(exclude={"superseded"}) for r in requirements],
        "preferences": draft.preferences,
        "production_constraints": draft.production_constraints,
        "assumptions": [a.model_dump() for a in draft.assumptions],
        "unknowns": draft.unknowns,
        "questions": [q.model_dump() for q in questions]
        + [q.model_dump() for q in draft.questions],
    }


def stable_references(card: TaskCard, ctx: RunContext) -> None:
    """Agents cite short run-local ids; the card keeps references that outlive the run."""
    evidences = [e for r in card.requirements for e in r.sources]
    evidences += [e for r in card.requirements for s in r.superseded for e in s.sources]
    evidences += [e for q in card.questions for e in q.sources]
    for evidence in evidences:
        source = ctx.sources.get(evidence.source_id)
        if source is not None:
            evidence.source_id = source.ref


def summary(card: TaskCard) -> str:
    text = _outcome(card)
    remarks = (
        [r.text for r in card.verdict.remarks if r.severity != "minor"] if card.verdict else []
    )
    if remarks:
        text += ". Проверка отметила " + ". ".join(remarks)
    return text


def _outcome(card: TaskCard) -> str:
    if card.readiness != "blocked":
        return "Задание разобрано, передаю на подбор параметров"
    open_questions = sum(not known(q.answer) for q in card.questions)
    if open_questions:
        return f"Задание разобрано, нужны ответы на вопросы, всего {open_questions}"
    return "Задание разобрано, но подбор параметров пока заблокирован"


def reading_text(reading: Any) -> str:
    if reading is None or not reading.value:
        return ""
    return f"{reading.value} {reading.unit or ''}".strip()
