import pytest

from src.backend.domain.models import (
    Assumption,
    Geometry,
    Question,
    Requirement,
    TaskCard,
)
from src.backend.domain.rules import assess, known

pytestmark = pytest.mark.unit


def card(**extra) -> TaskCard:
    base = {
        "job_id": "j",
        "revision": 1,
        "geometry": Geometry(readable=True, units="mm", extents=[10, 20, 30]),
        "requirements": [Requirement(key="t", value="1", verified=True)],
    }
    return TaskCard(**{**base, **extra})


@pytest.mark.parametrize("value", [None, "", " Не знаю ", "unknown", "неизвестно"])
def test_dont_know_is_not_an_answer(value):
    assert not known(value)


def test_ready_card_allows_parameter_selection():
    result = assess(card(), [])
    assert result.readiness == "ready"
    assert result.allowed_actions == ["select_parameters"] and result.blocked_actions == {}


@pytest.mark.parametrize(
    "extra,failed,reason",
    [
        ({"geometry": None}, [], "Нужна читаемая модель STL"),
        ({"questions": [Question(id="q", kind="clarify", title="Какая среда")]}, [], "Какая"),
        ({}, ["ТЗ.pdf"], "Не прочитаны файлы ТЗ.pdf"),
    ],
)
def test_blockers(extra, failed, reason):
    result = assess(card(**extra), failed)
    assert result.readiness == "blocked" and result.allowed_actions == []
    assert any(reason in r for r in result.blocked_actions["select_parameters"])


def test_answered_dont_know_still_blocks_a_blocking_question():
    question = Question(id="q", kind="clarify", title="Какая среда", answer="Не знаю")
    assert assess(card(questions=[question]), []).readiness == "blocked"


@pytest.mark.parametrize(
    "extra",
    [
        {"assumptions": [Assumption(text="Комнатная влажность")]},
        {"unknowns": ["Срок службы"]},
        {"geometry": Geometry(readable=True, defects=["boundary_edges"])},
        {"questions": [Question(id="q", kind="clarify", title="Цвет", blocking=False)]},
    ],
)
def test_caveats_make_the_card_preliminary(extra):
    assert assess(card(**extra), []).readiness == "preliminary"


def test_an_unverified_requirement_does_not_block():
    # A value without a source is an assumption the user is told about, not a blocker.
    unverified = Requirement(key="color", value="чёрный")
    assert assess(card(requirements=[unverified]), []).readiness == "ready"
