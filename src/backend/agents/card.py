from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from ..domain.hashing import digest
from ..domain.models import (
    Assumption,
    Evidence,
    Question,
    Requirement,
    Source,
    Superseded,
    TaskCard,
    WaivedQuestion,
)
from ..domain.requirement_keys import RequirementKeys
from ..domain.rules import known
from .runner import RunContext
from .schemas import (
    Citation,
    CodeFix,
    CodeValue,
    DraftAssumption,
    DraftQuestion,
    DraftRequirement,
    DraftWithCodes,
    Review,
    ReviewQuestion,
)

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "ё": "е", "«": '"', "»": '"'})
_NOT_KEY = re.compile(r"[^a-z0-9_]+")
# расхождения становятся вопросами
DISCREPANCIES = {"tz_vs_stl", "capability", "defect_vs_purpose", "sources", "discrepancy"}
# кто назвал значение
ORIGIN = {"message": "user", "answer": "user", "document": "document", "knowledge": "knowledge"}
# подмена источника
ASSUMED = "assumption"
ANSWER = "a:"
SETTLED = "Источники расходились, значение выбрано при проверке"


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().translate(_DASHES).split())


def clean_key(key: str) -> str:
    """Допустимый свободный ключ требования."""
    text = _NOT_KEY.sub("_", key.strip().casefold()).strip("_")
    return text if text[:1].isalpha() else "req_" + text


class WorkingCard(BaseModel):
    """Рабочий черновик карточки с идентификаторами."""

    purpose: str = ""
    requirements: dict[str, DraftRequirement] = Field(default_factory=dict)
    codes: dict[str, CodeValue] = Field(default_factory=dict)
    preferences: list[str] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    assumptions: list[DraftAssumption] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    questions: list[DraftQuestion] = Field(default_factory=list)
    # значения спорного кода
    superseded: dict[str, list[DraftRequirement]] = Field(default_factory=dict)
    next_id: int = 1

    @classmethod
    def from_draft(cls, draft: DraftWithCodes, keys: RequirementKeys) -> WorkingCard:
        card = cls(
            purpose=draft.purpose,
            codes=draft.codes.filled(),
            preferences=draft.preferences,
            production_constraints=draft.production_constraints,
            assumptions=draft.assumptions,
            unknowns=draft.unknowns,
            questions=draft.questions,
        )
        for requirement in draft.requirements:
            card.add(requirement, keys)
        card.normalise(keys)
        return card

    def add(self, requirement: DraftRequirement, keys: RequirementKeys, at: str = "") -> None:
        """Добавление требования в рабочую карточку."""
        requirement = requirement.model_copy(update={"key": clean_key(requirement.key)})
        key = requirement.key
        if keys.get(key) is not None:
            held = self.codes.get(key)
            if held is None and not self._disputed(key) or held is not None and held.inferred:
                self.codes[key] = _code(requirement)
                return
            if held is not None and _agrees(held, requirement, keys):
                return
            if held is not None:
                del self.codes[key]
                self._keep(_from_code(key, held))
        self._keep(requirement, at)

    def _keep(self, requirement: DraftRequirement, at: str = "") -> None:
        if not at:
            at, self.next_id = f"r{self.next_id}", self.next_id + 1
        self.requirements[at] = requirement

    def _disputed(self, code: str) -> bool:
        return any(r.key == code for r in self.requirements.values())

    def _settle(self, code: str) -> None:
        """Закрытие спора по коду."""
        for at, requirement in list(self.requirements.items()):
            if requirement.key == code:
                self.superseded.setdefault(code, []).append(self.requirements.pop(at))

    def normalise(self, keys: RequirementKeys) -> None:
        """Приведение значения кода к виду."""
        for code, value in list(self.codes.items()):
            entry = keys.get(code)
            read = keys.normalise(code, value.value, value.unit)
            if entry is None or read is None:
                del self.codes[code]
                title = entry.title if entry else code
                self.unknowns.append(f"{title}, значение «{value.value}» не распознано")
            else:
                self.codes[code] = value.model_copy(update={"value": read[0], "unit": read[1]})

    def view(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "requirements": [{"id": i, **r.model_dump()} for i, r in self.requirements.items()],
            "codes": {code: value.model_dump() for code, value in self.codes.items()},
            "preferences": self.preferences,
            "production_constraints": self.production_constraints,
            "assumptions": [a.model_dump() for a in self.assumptions],
            "unknowns": self.unknowns,
            "questions": [
                {"id": f"q{number}", **q.model_dump()} for number, q in enumerate(self.questions, 1)
            ],
        }

    def apply(self, review: Review, keys: RequirementKeys) -> None:
        """Применение правок проверяющего к карточке."""
        for item in review.change:
            if self.requirements.pop(item.id, None) is not None:
                self.add(DraftRequirement(**item.model_dump(exclude={"id"})), keys, item.id)
        for removal in review.remove:
            self.requirements.pop(removal.id, None)
        for requirement in review.add:
            self.add(requirement, keys)
        for fix in review.code_fixes:
            if keys.get(fix.code) is None:
                continue
            if fix.value is None or not fix.value.strip():
                self.codes.pop(fix.code, None)
            else:
                self.codes[fix.code] = _fixed(self.codes.get(fix.code), fix)
                self._settle(fix.code)
        seen = {normalize_text(a.text) for a in self.assumptions}
        for assumption in review.assumptions:
            if normalize_text(assumption.text) not in seen:
                seen.add(normalize_text(assumption.text))
                self.assumptions.append(assumption)
        self.normalise(keys)

    def requirements_for(self, keys: RequirementKeys, ctx: RunContext) -> list[Requirement]:
        """Требования в порядке словаря кодов."""
        coded = [
            coded_requirement(code, self.codes[code], keys, ctx, self.superseded.get(code, []))
            for code in (entry.key for entry in keys.keys)
            if code in self.codes
        ]
        return coded + [free_requirement(r, ctx) for r in self.requirements.values()]


def _fixed(held: CodeValue | None, fix: CodeFix) -> CodeValue:
    """Значение проверяющего поверх кода."""
    changes = fix.model_dump(include={"value", "unit", "source_id", "quote", "basis"})
    changes["inferred"] = fix.inferred and not (fix.source_id or "").startswith(ANSWER)
    if held is None:
        return CodeValue(**changes)
    if held.source_id != fix.source_id:
        changes.update(conditions="", mandatory=True, page=None)
    return held.model_copy(update=changes)


def _agrees(held: CodeValue, requirement: DraftRequirement, keys: RequirementKeys) -> bool:
    """Согласие источников и значений."""
    citation = requirement.sources[0] if requirement.sources else None
    if citation is None or citation.source_id == held.source_id:
        return True
    read = keys.normalise(requirement.key, requirement.value, requirement.unit)
    kept = keys.normalise(requirement.key, held.value, held.unit)
    if read is None or kept is None:
        return normalize_text(requirement.value) == normalize_text(held.value)
    return read == kept


def _from_code(key: str, value: CodeValue) -> DraftRequirement:
    sources = (
        [Citation(source_id=value.source_id, page=value.page, quote=value.quote)]
        if value.source_id
        else []
    )
    return DraftRequirement(
        key=key,
        label=value.label,
        value=value.value,
        unit=value.unit,
        conditions=value.conditions,
        mandatory=value.mandatory,
        sources=sources,
    )


def _code(requirement: DraftRequirement) -> CodeValue:
    citation = requirement.sources[0] if requirement.sources else None
    return CodeValue(
        value=requirement.value,
        unit=requirement.unit,
        label=requirement.label,
        conditions=requirement.conditions,
        mandatory=requirement.mandatory,
        source_id=citation.source_id if citation else None,
        page=citation.page if citation else None,
        quote=citation.quote if citation else "",
    )


def provenance(source_id: str | None, ctx: RunContext) -> str:
    """Происхождение значения по источнику."""
    source = ctx.sources.get(source_id or "")
    return ASSUMED if source is None else ORIGIN[source.kind]


def coded_requirement(
    code: str,
    value: CodeValue,
    keys: RequirementKeys,
    ctx: RunContext,
    superseded: Sequence[DraftRequirement] = (),
) -> Requirement:
    """Требование с кодом из значения."""
    origin = ASSUMED if value.inferred else provenance(value.source_id, ctx)
    entry = keys.get(code)
    citation = Evidence(source_id=value.source_id or ASSUMED, quote=value.quote, page=value.page)
    return Requirement(
        superseded=[
            Superseded(
                value=old.value,
                unit=old.unit,
                sources=[Evidence(**c.model_dump()) for c in old.sources],
                reason=SETTLED,
            )
            for old in superseded
        ],
        key=code,
        label=value.label or (entry.title if entry else code),
        value=value.value,
        unit=value.unit,
        conditions=(value.basis or value.conditions) if value.inferred else value.conditions,
        mandatory=value.mandatory and origin != ASSUMED,
        provenance=origin,  # type: ignore[arg-type]
        sources=[citation],
        verified=origin != ASSUMED,
    )


def free_requirement(draft: DraftRequirement, ctx: RunContext) -> Requirement:
    sources = [Evidence(**c.model_dump()) for c in draft.sources] or [Evidence(source_id=ASSUMED)]
    origin = provenance(sources[0].source_id, ctx)
    return Requirement(
        **draft.model_dump(exclude={"sources", "mandatory"}),
        mandatory=draft.mandatory and origin != ASSUMED,
        provenance=origin,  # type: ignore[arg-type]
        sources=sources,
        verified=origin != ASSUMED,
    )


def to_question(question: ReviewQuestion) -> Question:
    """Расхождение превращается в вопрос."""
    anchor = question.requirement_key or normalize_text(question.title)
    discrepancy = question.kind in DISCREPANCIES
    return Question(
        id=(f"{question.kind}." if discrepancy else "clarify.") + digest(anchor),
        kind="discrepancy" if discrepancy else "clarify",
        title=question.title,
        impact=question.impact,
        options=question.options,
        suggested=question.suggested if question.basis else None,
        basis=question.basis,
        requirement_key=question.requirement_key,
        blocking=True,
    )


def settle_questions(
    proposed: list[DraftQuestion], review: Review
) -> tuple[list[ReviewQuestion], list[WaivedQuestion]]:
    """Решение судьбы предложенных вопросов."""
    ids = {f"q{number}": q for number, q in enumerate(proposed, 1)}
    kept = {q.source for q in review.questions if q.source}
    reasons = {w.id: w.reason.strip() for w in review.waived if w.id in ids and w.id not in kept}
    reasons = {key: reason for key, reason in reasons.items() if reason}
    restored = [
        ReviewQuestion(**q.model_dump(), source=key)
        for key, q in ids.items()
        if key not in kept and key not in reasons
    ]
    waived = [WaivedQuestion(title=ids[key].title, reason=r) for key, r in reasons.items()]
    return [*review.questions, *restored], waived


def merged(questions: list[Question], answers: dict[str, str]) -> list[Question]:
    """Объединение вопросов по идентификатору."""
    unique: dict[str, Question] = {}
    for question in questions:
        unique.setdefault(question.id, question)
    for question in unique.values():
        question.answer = answers.get(question.id)
    return list(unique.values())


def fill(card: TaskCard, working: WorkingCard, requirements: list[Requirement]) -> TaskCard:
    card.purpose = working.purpose
    card.requirements = requirements
    card.preferences = working.preferences
    card.production_constraints = working.production_constraints
    card.assumptions = [Assumption(**a.model_dump()) for a in working.assumptions]
    card.unknowns = list(dict.fromkeys(working.unknowns))
    return card


def stable_references(card: TaskCard, ctx: RunContext) -> None:
    """Устойчивые ссылки вместо коротких идентификаторов."""
    evidences = [e for r in card.requirements for e in r.sources]
    evidences += [e for r in card.requirements for old in r.superseded for e in old.sources]
    evidences += [e for q in card.questions for e in q.sources]
    for evidence in evidences:
        source = ctx.sources.get(evidence.source_id)
        if source is not None:
            # страница хранит изображение
            evidence.page, evidence.artifact_id = source.page, source.image
            evidence.method = _method(source)  # type: ignore[assignment]
            evidence.source_id = source.ref


def _method(source: Source) -> str:
    """Способ проверки цитаты источника."""
    if source.kind != "document":
        return ORIGIN[source.kind]
    return "vision" if not source.text.strip() and source.image else "text"


def summary(card: TaskCard) -> str:
    if card.readiness != "blocked":
        return "Задание разобрано, передаю на подбор параметров"
    open_questions = sum(not known(q.answer) for q in card.questions)
    if open_questions:
        return f"Задание разобрано, нужны ответы на вопросы, всего {open_questions}"
    return "Задание разобрано, но подбор параметров пока заблокирован"
