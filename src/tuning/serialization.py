"""Deterministic JSON output shared by the library and the CLI."""

import json
from typing import Any  # noqa: F401  (used in type comments)


def dumps(payload):
    # type: (Any) -> str
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def load_json_file(path):
    # type: (str) -> dict
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)
