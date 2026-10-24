import json
from pathlib import Path

import pytest

from src.backend.domain.models import TaskCard
from src.backend.domain.parameters import Feedback, ParameterSet

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "model"),
    [
        ("docs/task-card-v2.0.schema.json", TaskCard),
        ("docs/parameter-set-v0.2.schema.json", ParameterSet),
        ("docs/stage3-feedback-v0.1.schema.json", Feedback),
    ],
)
def test_published_schema_matches_the_code(path, model):
    published = json.loads(Path(path).read_text())
    for key in ("$schema", "$id"):
        published.pop(key)
    assert published == model.model_json_schema()
