import pytest

from src.backend.domain.evidence import merge_cards, validate_evidence
from src.backend.domain.models import Evidence, Requirement, TaskCard
from src.backend.domain.rules import assess

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["80", "100,5", "0", "-10", "15"])
def test_user_correction_replaces_unverified_value(value):
    from src.backend.domain.evidence import apply_answers

    card = validate_evidence(
        TaskCard(requirements=[Requirement(key="size", label="Размер", value="100")]), {}
    )
    question = card.questions[0]
    apply_answers(card, {question.id: value}, {}, "answer-source")
    assert card.requirements[0].value == value
    assert card.requirements[0].verified
    assert card.requirements[0].sources[0].source_id == "answer-source"


@pytest.mark.parametrize("answer", ["да", "готово", "mm", "любое", "100"])
def test_model_cannot_supply_its_own_answers(answer):
    from src.backend.domain.models import Geometry, Question

    card = TaskCard(
        purpose="gear",
        geometry=Geometry(readable=True, units="mm"),
        questions=[
            Question(id="load", title="Load", reason="Required", answer=answer, affected_actions=[])
        ],
    )
    assert assess(card).readiness == "blocked"


@pytest.mark.parametrize("count", [1, 2, 5, 10, 50])
def test_conflicts_group_values_without_pairwise_explosion(count):
    cards = [TaskCard(requirements=[Requirement(key="size", value=str(i))]) for i in range(count)]
    result = merge_cards(cards)
    assert len(result.conflicts) == (1 if count > 1 else 0)


@pytest.mark.parametrize("number", ["1", "10", "25", "75", "160"])
def test_T03_number_not_in_quote_requires_verification(number):
    card = TaskCard(
        requirements=[
            Requirement(
                key="load",
                value=number,
                sources=[Evidence(source_id="doc", quote="No measured values")],
            )
        ]
    )
    result = validate_evidence(card, {"doc": {"text": "No measured values"}})
    assert not result.requirements[0].verified
    assert result.questions


def test_T08_approval_does_not_transfer_to_changed_conflict():
    first = merge_cards(
        [
            TaskCard(
                requirements=[
                    Requirement(key="size", value="80"),
                    Requirement(key="size", value="100"),
                ]
            )
        ]
    )
    changed = merge_cards(
        [
            TaskCard(
                requirements=[
                    Requirement(key="size", value="90"),
                    Requirement(key="size", value="100"),
                ]
            )
        ]
    )
    assert first.conflicts[0].id != changed.conflicts[0].id


def test_visual_requirement_keeps_page_and_image_evidence():
    result = validate_evidence(
        TaskCard(
            requirements=[
                Requirement(
                    key="nominal",
                    value="25",
                    sources=[Evidence(source_id="scan:1", quote="Nominal 25 Nm", page=1)],
                )
            ]
        ),
        {"scan:1": {"text": "", "method": "vision", "image": "scan-page-1.png", "page": 1}},
    )
    requirement = result.requirements[0]
    assert requirement.verified
    assert requirement.sources[0].method == "vision"
    assert requirement.sources[0].artifact_id == "scan-page-1.png"
    assert not result.questions


@pytest.mark.parametrize(
    "case",
    [
        "missing_source",
        "missing_page",
        "wrong_page",
        "missing_image",
        "wrong_number",
        "uncertain",
        "unreadable",
    ],
)
def test_visual_requirement_cannot_bypass_source_checks(case):
    source = {
        "text": "",
        "method": "vision",
        "image": "scan-page-1.png",
        "page": 1,
        "uncertain": case == "uncertain",
    }
    if case == "missing_image":
        source.pop("image")
    requirement = Requirement(
        key="nominal",
        value="75" if case == "wrong_number" else "25",
        verified=case != "unreadable",
        sources=[
            Evidence(
                source_id="missing" if case == "missing_source" else "scan:1",
                quote="Nominal 25 Nm",
                page=None if case == "missing_page" else 2 if case == "wrong_page" else 1,
            )
        ],
    )
    result = validate_evidence(TaskCard(requirements=[requirement]), {"scan:1": source})
    assert not result.requirements[0].verified
    assert result.questions
