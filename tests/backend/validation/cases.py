"""Parameter sets of tests/fixtures/validation and what the original check found in them.

Each fixture holds a parameter set in contract 0.2, the ``case`` it stands for and the
``original`` findings ``[level, where, message]`` of FedorSolodkin's
``validation/tools/check_parameter_set.py`` (commit c271306) on the same JSON with ``version``
set to "0.1", the only field of 0.2 that check reads differently. ``example_*`` is the
contract's example, ``selftest_*`` the original's selftest mutations of it, ``extra_*``
mutations reaching the branches that selftest does not, and ``stage2_*`` outputs of parameter
selection on stage-one cards.
"""

import json
from pathlib import Path
from typing import Any

from src.backend.domain.parameters import ParameterSet

FIXTURES = Path("tests/fixtures/validation")
NAMES = sorted(path.stem for path in FIXTURES.glob("*.json"))
# Original findings ParameterSet now refuses on its own: the printing mode is one of three
# literals, ``why`` is required on every value, the iteration is 1 or 2.
REFUSED_BY_THE_CONTRACT = {
    "selftest_discrete_mode": [("error", "printing_mode")],
    "selftest_missing_reason": [("error", "settings.wall_line_count")],
    "selftest_iteration_3": [("error", "iteration")],
}
PORTED = [name for name in NAMES if name not in REFUSED_BY_THE_CONTRACT]


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def parameter_set(name: str) -> ParameterSet:
    return ParameterSet.model_validate(load(name)["parameter_set"])
