"""The ported selection reproduces the outputs of the original code, see
``tests/fixtures/tuning/README.md``."""

import json
from pathlib import Path

import pytest

from src.backend.domain.models import TaskCard
from src.backend.domain.parameters import Feedback

pytestmark = pytest.mark.unit
FIXTURES = Path("tests/fixtures/tuning")
CASES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


def with_agreed_differences(expected: dict, card: TaskCard) -> dict:
    """The contract 0.2 and the 2.0 card are the only changes the port is allowed."""
    changed = {key: value for key, value in expected.items() if key != "idempotency_key"}
    changed["version"] = "0.2"
    changed["card_ref"] = {"job_id": card.job_id, "revision": card.revision}
    changed["warnings"] = [
        text for text in expected["warnings"] if text != "bare task card without idempotency_key"
    ]
    changed["models"] = [
        {
            **model,
            "transform": {
                **model["transform"],
                "rotation": [[float(v) for v in row] for row in model["transform"]["rotation"]],
                "scale": [float(v) for v in model["transform"]["scale"]],
            },
        }
        for model in expected["models"]
    ]
    return changed


def dumped(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def test_golden_cases_cover_the_author_cards_and_the_eval_run():
    assert len(CASES) == 38
    assert sum(name.startswith("eval-") for name in CASES) == 7
    assert sum((FIXTURES / name / "feedback.json").exists() for name in CASES) == 9


@pytest.mark.parametrize("name", CASES)
def test_ported_selection_matches_the_original_output(select, name):
    folder = FIXTURES / name
    card = TaskCard.model_validate_json((folder / "card.json").read_text(encoding="utf-8"))
    review = folder / "feedback.json"
    feedback = Feedback.model_validate_json(review.read_text()) if review.exists() else None
    expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    assert dumped(select(card, feedback)) == dumped(with_agreed_differences(expected, card))
