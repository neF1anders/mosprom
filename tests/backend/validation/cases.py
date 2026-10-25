import json
from pathlib import Path
from typing import Any

from src.backend.domain.parameters import ParameterSet

FIXTURES = Path("tests/fixtures/validation")
NAMES = sorted(path.stem for path in FIXTURES.glob("*.json"))
# отклоняет ParameterSet
REFUSED_BY_THE_CONTRACT = {
    "selftest_discrete_mode": [("error", "printing_mode")],
    "selftest_missing_reason": [("error", "settings.wall_line_count")],
    "selftest_iteration_3": [("error", "iteration")],
}
PORTED = [name for name in NAMES if name not in REFUSED_BY_THE_CONTRACT]
# сборка глубже оригинала
BEYOND_THE_ORIGINAL: dict[str, list[tuple[str, str]]] = {
    "extra_fdmprinter_formula_default": [],
    "extra_formula_unknown": [("warning", "settings.connect_infill_polygons")],
}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def parameter_set(name: str) -> ParameterSet:
    return ParameterSet.model_validate(load(name)["parameter_set"])
