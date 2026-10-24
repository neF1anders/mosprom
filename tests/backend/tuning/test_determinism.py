import json

import pytest

from tests.backend.tuning.cards import card, constraint, feedback, requirement

pytestmark = pytest.mark.unit

CARD = dict(
    requirements=[requirement("load_bearing", "ударная нагрузка")],
    preferences=["прочность, затем скорость"],
)


def dumped(parameter_set):
    return json.dumps(parameter_set, sort_keys=True, ensure_ascii=False)


def test_same_card_and_feedback_give_identical_bytes(select):
    review = feedback(constraint("C1", "infill_sparse_density", "max", 25))
    assert dumped(select(card(**CARD))) == dumped(select(card(**CARD)))
    assert dumped(select(card(**CARD), review)) == dumped(select(card(**CARD), review))
