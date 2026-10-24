"""Requirement codes: how the server checks coded values."""

from pathlib import Path

import pytest

from src.backend.agents.context import ContentBuilder, collect
from src.backend.agents.runner import AgentRunner
from src.backend.agents.schemas import Draft
from src.backend.agents.tools import ToolBox
from src.backend.agents.verification import Verifier
from src.backend.domain.evidence import reference
from src.backend.domain.models import Requirement, Source
from src.backend.infrastructure.catalog import load_requirement_keys

from .fakes import FakeUow, ScriptedModel, context

pytestmark = pytest.mark.unit
CODES = load_requirement_keys(Path("knowledge/requirement_keys.json"))
MESSAGE = "Шестерня, номинальный момент 25 Нм, рабочая температура до 80 °C"


def test_a_coded_number_fits_only_a_unit_of_the_same_quantity():
    assert CODES.unit_mismatch("service_temp_max_c", "°С") is None
    assert CODES.unit_mismatch("density_max_g_cm3", "кг/м³") is None
    assert CODES.unit_mismatch("service_temp_max_c", "мм") == "°C"
    assert CODES.unit_mismatch("dimensional_tol_mm", None) == "mm"
    assert CODES.unit_mismatch("quantity", "шт") is None
    assert CODES.unit_mismatch("temperature_operating", "мм") is None


def coded_draft(unit: str, mandatory: bool = True) -> Draft:
    return Draft.model_validate(
        {
            "requirements": [
                {
                    "key": "service_temp_max_c",
                    "label": "Рабочая температура",
                    "value": "80",
                    "unit": unit,
                    "mandatory": mandatory,
                    "sources": [{"source_id": "m1", "quote": "рабочая температура до 80 °C"}],
                }
            ]
        }
    )


async def verify(draft: Draft, answers: dict[str, str]):
    ctx = context()
    ctx.sources["m1"] = Source(id="m1", ref="u1", kind="message", text=MESSAGE)
    verifier = Verifier(AgentRunner(ScriptedModel({}), ToolBox(None), FakeUow()), CODES)
    return await verifier.check(
        draft, answers, ContentBuilder(None, collect([], [], {}, None), ctx), ctx
    )


async def test_a_coded_number_in_a_unit_of_another_quantity_is_asked_not_verified():
    requirements, questions = await verify(coded_draft("°C"), {})
    assert requirements[0].verified and questions == []
    requirements, questions = await verify(coded_draft("мм"), {})
    assert [(r.key, r.value, r.unit, r.verified) for r in requirements] == [
        ("service_temp_max_c", "80", "мм", False)
    ]
    assert [(q.kind, q.blocking, q.options) for q in questions] == [("verify", True, [])]
    assert "°C" in questions[0].impact and questions[0].requirement_key == "service_temp_max_c"
    requirements, questions = await verify(coded_draft("мм", mandatory=False), {})
    assert not requirements[0].verified and questions == []


@pytest.mark.parametrize(
    "answer,unit,verified", [("80", "°C", True), ("75 °C", "°C", True), ("80 мм", "мм", False)]
)
async def test_an_answer_gives_the_coded_value_a_unit_selection_can_read(answer, unit, verified):
    stated = coded_draft("мм")
    question = "verify." + reference(
        Requirement(**stated.requirements[0].model_dump(exclude={"sources"}))
    )
    requirements, _ = await verify(stated, {question: answer})
    assert (requirements[0].unit, requirements[0].verified) == (unit, verified)
    assert requirements[0].provenance == "user"