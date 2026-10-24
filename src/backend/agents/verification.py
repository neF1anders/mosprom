"""Code checks each requirement against its sources; an image reading needs a second reader."""

from __future__ import annotations

import json
from typing import Any

from ..domain.evidence import (
    apply_decision,
    check_citations,
    display,
    reconcile,
    reference,
    same_quantity,
    verify_question,
)
from ..domain.models import Question, Requirement
from ..domain.requirement_keys import RequirementKeys
from ..domain.rules import known
from .card import reading_text, to_requirement
from .concurrency import together
from .context import ContentBuilder
from .runner import AgentRunner, AgentSpec, RunContext
from .schemas import Draft, SecondReading

SECOND_READER = AgentSpec(
    "second_reading", "Второе чтение", SecondReading, max_steps=1, budget=4000
)


class Verifier:
    def __init__(self, runner: AgentRunner, codes: RequirementKeys):
        self.runner, self.codes = runner, codes

    async def check(
        self, draft: Draft, answers: dict[str, str], content: ContentBuilder, ctx: RunContext
    ) -> tuple[list[Requirement], list[Question]]:
        checked, questions, pending = [], [], []
        for requirement in map(to_requirement, draft.requirements):
            question_id = "verify." + reference(requirement)
            if known(answers.get(question_id)):
                questions.append(verify_question(requirement, "Значение подтверждено вами", []))
                checked.append(self._decide(requirement, question_id, answers[question_id]))
                continue
            status = check_citations(requirement, ctx.sources)
            expected = self.codes.unit_mismatch(requirement.key, requirement.unit)
            if expected is not None:
                status = "rejected"
            requirement.verified = status == "verified"
            if status == "vision":
                pending.append(requirement)
            elif status == "rejected" and requirement.mandatory:
                questions.append(_unverified(requirement, expected))
            checked.append(requirement)
        for requirement, reading in await self._second_reading(pending, content, ctx):
            if requirement.mandatory:
                impact = "Значение прочитано с изображения по-разному"
                questions.append(
                    verify_question(requirement, impact, [display(requirement), reading])
                )
        merged, conflicts = reconcile(checked, ctx.sources, answers)
        for requirement in merged:
            # Neither a decision nor a choice between sources makes such a unit readable.
            fits = self.codes.unit_mismatch(requirement.key, requirement.unit) is None
            requirement.verified = requirement.verified and fits
        return merged, questions + conflicts

    def _decide(self, requirement: Requirement, question_id: str, answer: str) -> Requirement:
        """A bare number answered for a coded value in a wrong unit takes the code's unit."""
        expected = self.codes.unit_mismatch(requirement.key, requirement.unit)
        asked = requirement.model_copy(update={"unit": expected or requirement.unit})
        return apply_decision(asked, question_id, answer, [requirement])

    async def _second_reading(
        self, pending: list[Requirement], content: ContentBuilder, ctx: RunContext
    ) -> list[tuple[Requirement, str]]:
        """Image readings count only when an independent reading of the page agrees.

        Pages are read side by side, so many image values cost one round trip.
        """
        by_source: dict[str, list[Requirement]] = {}
        for requirement in pending:
            for evidence in requirement.sources:
                if evidence.method == "vision":
                    by_source.setdefault(evidence.source_id, []).append(requirement)
        pages = await together(
            *(self._read_page(source, items, content, ctx) for source, items in by_source.items())
        )
        mismatches: dict[int, tuple[Requirement, str]] = {}
        for requirements, readings in zip(by_source.values(), pages):
            for requirement in requirements:
                reading = readings.get(requirement.key)
                agrees = (
                    reading is not None
                    and reading.legible
                    and same_quantity(requirement, reading.value, reading.unit or requirement.unit)
                )
                if not agrees:
                    mismatches[id(requirement)] = (requirement, reading_text(reading))
        for requirement in pending:
            requirement.verified = id(requirement) not in mismatches
        return list(mismatches.values())

    async def _read_page(
        self,
        source_id: str,
        requirements: list[Requirement],
        content: ContentBuilder,
        ctx: RunContext,
    ) -> dict[str, Any]:
        source = ctx.sources[source_id]
        items = [
            {"key": r.key, "label": r.label, "conditions": r.conditions, "unit": r.unit}
            for r in requirements
        ]
        text = "<items>\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n</items>"
        parts = [{"type": "text", "text": text}]
        parts.extend(await content.image(source.image or "", f"Страница {source.id}"))
        reading = await self.runner.run(SECOND_READER, parts, ctx)
        return {r.key: r for r in reading.readings}


def _unverified(requirement: Requirement, expected: str | None) -> Question:
    """A value without a literal quote may be confirmed as stated; a coded value in a unit of
    another quantity needs a new value, so the stated one is not offered."""
    if expected is None:
        impact = "Значение не найдено в источнике дословно"
        return verify_question(requirement, impact, [display(requirement)])
    return verify_question(requirement, f"Для подбора параметров нужно значение в {expected}", [])
