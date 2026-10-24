from datetime import datetime, timedelta, timezone

import pytest

from src.backend.domain.evidence import (
    apply_decision,
    check_citations,
    reconcile,
    reference,
)
from src.backend.domain.models import Evidence, Requirement, Source

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 23, tzinfo=timezone.utc)
SOURCES = {
    "m1": Source(id="m1", ref="msg-1", kind="message", text="Момент 30 Н·м", created_at=T0),
    "m2": Source(
        id="m2",
        ref="msg-2",
        kind="message",
        text="Нет, момент 35 Н·м",
        created_at=T0 + timedelta(1),
    ),
    "f1p1": Source(
        id="f1p1", ref="att:1", kind="document", text="Номинальный  момент\n25 Н·м", page=1
    ),
    "f2p1": Source(id="f2p1", ref="att2:1", kind="document", text="Момент 28 Н·м", page=1),
    "f3p2": Source(
        id="f3p2",
        ref="pdf:2",
        kind="document",
        text="Номинальный момент 25 Н·м",
        page=2,
        image="p2.png",
    ),
    "f4p1": Source(id="f4p1", ref="scan:1", kind="document", text="", page=1, image="s1.png"),
}


def requirement(value="25", quote="Номинальный момент 25 Н·м", source="f1p1", **extra):
    data = {
        "key": "torque_nominal",
        "label": "Номинальный момент",
        "value": value,
        "unit": "Н·м",
        "sources": [Evidence(source_id=source, quote=quote)],
    }
    return Requirement(**{**data, **extra})


def test_literal_quote_with_matching_numbers_is_verified():
    r = requirement()
    assert check_citations(r, SOURCES) == "verified"
    assert r.sources[0].method == "text" and r.sources[0].page == 1


@pytest.mark.parametrize(
    "case",
    [
        requirement(value="250"),
        requirement(quote="Номинальный момент 250 Н·м"),
        requirement(source="missing"),
        requirement(quote=""),
        requirement(provenance="assumption"),
        requirement(sources=[]),
        requirement(
            sources=[Evidence(source_id="f1p1", quote="Номинальный момент 25 Н·м", page=3)]
        ),
    ],
)
def test_unsupported_citations_are_rejected(case):
    assert check_citations(case, SOURCES) == "rejected"


def test_text_layer_quote_is_text_even_on_a_page_with_an_image():
    r = requirement(source="f3p2", quote="Номинальный момент 25 Н·м")
    assert check_citations(r, SOURCES) == "verified"
    assert r.sources[0].method == "text" and r.sources[0].artifact_id == "p2.png"


@pytest.mark.parametrize("source", ["f3p2", "f4p1"])
def test_quote_absent_from_text_layer_needs_second_reading(source):
    """A fabricated quote on a PDF page is never verified on the model's word alone."""
    r = requirement(value="250", quote="момент 250 Н·м", source=source)
    assert check_citations(r, SOURCES) == "vision"
    assert r.sources[0].method == "vision"


def test_user_message_wins_over_documents_and_newest_message_wins():
    document = requirement()
    first = requirement(value="30", quote="Момент 30 Н·м", source="m1", provenance="user")
    second = requirement(value="35", quote="момент 35 Н·м", source="m2", provenance="user")
    for r in (document, first, second):
        assert check_citations(r, SOURCES) == "verified"
    merged, questions = reconcile([document, first, second], SOURCES, {})
    assert questions == []
    assert [r.value for r in merged] == ["35"]
    assert {s.value for s in merged[0].superseded} == {"25", "30"}
    assert all(s.reason == "Заменено сообщением пользователя" for s in merged[0].superseded)


def test_disagreeing_documents_go_to_the_user_and_the_answer_is_applied():
    a = requirement()
    b = requirement(value="28", quote="Момент 28 Н·м", source="f2p1")
    for r in (a, b):
        check_citations(r, SOURCES)
    merged, questions = reconcile([a, b], SOURCES, {})
    assert len(questions) == 1 and questions[0].options == ["25 Н·м", "28 Н·м"]
    assert merged[0].verified is False
    merged, _ = reconcile([a, b], SOURCES, {questions[0].id: "28 Н·м"})
    assert (merged[0].value, merged[0].unit, merged[0].provenance) == ("28", "Н·м", "user")
    assert merged[0].verified and [s.value for s in merged[0].superseded] == ["25"]


def test_equivalent_values_are_not_a_conflict():
    a = requirement()
    b = requirement(value="25000", quote="Момент 28 Н·м", source="f2p1", unit="Н·мм")
    merged, questions = reconcile([a, b], SOURCES, {})
    assert questions == [] and len(merged) == 1


def test_different_conditions_are_different_properties():
    nominal = requirement()
    peak = requirement(value="75", conditions="пик при стопорении")
    merged, questions = reconcile([nominal, peak], SOURCES, {})
    assert questions == [] and len(merged) == 2
    assert reference(nominal) != reference(peak)


@pytest.mark.parametrize(
    "answer,value,unit",
    [
        ("27", "27", "Н·м"),
        ("27 Н·м", "27", "Н·м"),
        ("0,027 кН·м", "0,027", "кН·м"),
        ("около тридцати", "около тридцати", None),
    ],
)
def test_custom_answers_replace_value(answer, value, unit):
    result = apply_decision(requirement(), "verify.x", answer, [requirement()])
    assert (result.value, result.unit, result.verified) == (value, unit, True)
    assert result.sources[0].source_id == "answer:verify.x"
