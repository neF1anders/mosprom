import pytest

from src.backend.domain.evidence import validate_evidence
from src.backend.domain.models import TaskCard
from src.backend.services.pipeline import source_batches

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("length", [0, 1, 9999, 10000, 25001])
def test_all_source_characters_are_covered(length):
    source = {"a": {"text": "x" * length, "page": 1}}
    batches = list(source_batches(source))
    assert "".join(b["a"]["text"] for b in batches) == source["a"]["text"]
    assert all(sum(len(v["text"]) for v in b.values()) <= 10000 for b in batches)


@pytest.mark.parametrize("case", ["forged", "empty", "uncertain", "assumption", "different"])
def test_unsupported_evidence_cannot_become_verified(case):
    from src.backend.domain.models import Evidence, Requirement

    source = {"a": {"text": "80 mm", "uncertain": case == "uncertain"}}
    r = Requirement(
        key="size",
        value="80",
        sources=[
            Evidence(
                source_id="b" if case == "forged" else "a",
                quote="" if case == "empty" else "100 mm" if case == "different" else "80 mm",
            )
        ],
        provenance="assumption" if case == "assumption" else "document",
    )
    card = validate_evidence(TaskCard(requirements=[r]), source)
    assert not card.requirements[0].verified
    assert card.questions


@pytest.mark.parametrize("count", [1, 3, 4, 20, 50])
def test_image_batches_preserve_coverage_and_bound_context(count):
    sources = {str(i): {"text": "", "image": str(i)} for i in range(count)}
    batches = list(source_batches(sources))
    assert sum(len(b) for b in batches) == count
    assert all(len(b) <= 3 for b in batches)
