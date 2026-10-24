import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.backend.domain.models import TaskCard
from src.backend.domain.parameters import Feedback, ParameterSet
from src.backend.infrastructure.catalog import load_requirement_keys

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


def test_stage_two_contract_example_is_a_valid_card():
    contract = json.loads(Path("docs/stage1-contract.schema.json").read_text())
    Draft202012Validator.check_schema(contract)
    example = {key: value for key, value in contract["examples"][0].items() if key != "_comment"}
    Draft202012Validator(contract).validate(example)
    TaskCard.model_validate(example)


def test_stage_two_contract_names_the_shared_codes():
    contract = json.loads(Path("docs/stage1-contract.schema.json").read_text())
    codes = load_requirement_keys(Path("knowledge/requirement_keys.json"))
    assert list(contract["$defs"]["RequirementCodes"]["properties"]) == [
        entry.key for entry in codes.keys
    ]
