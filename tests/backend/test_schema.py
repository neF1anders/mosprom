import json
from pathlib import Path

import pytest

from src.backend.domain.models import TaskCard

pytestmark = pytest.mark.unit


def test_published_card_schema_matches_the_code():
    published = json.loads(Path("docs/task-card-v2.0.schema.json").read_text())
    for key in ("$schema", "$id"):
        published.pop(key)
    assert published == TaskCard.model_json_schema()
