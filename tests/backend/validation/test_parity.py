"""The port finds what the original check found, place by place and in the same order.

The original's findings are stored in each fixture. Those ``ParameterSet`` now refuses on its
own are not checked again, and where the port reads the build more fully it finds what
``cases`` lists instead.
"""

import pytest
from pydantic import ValidationError

from src.backend.domain.parameters import ParameterSet
from src.backend.validation.checks import check_parameters

from .cases import BEYOND_THE_ORIGINAL, PORTED, REFUSED_BY_THE_CONTRACT, load, parameter_set

pytestmark = pytest.mark.unit


def original(name: str) -> list[tuple[str, str]]:
    return [(level, where) for level, where, _ in load(name)["original"]]


@pytest.mark.parametrize("name", [name for name in PORTED if name not in BEYOND_THE_ORIGINAL])
def test_port_finds_what_the_original_found(name, catalog):
    found = check_parameters(parameter_set(name), catalog)
    assert [(issue.level, issue.where) for issue in found] == original(name)


@pytest.mark.parametrize("name", BEYOND_THE_ORIGINAL)
def test_port_reads_formulas_the_original_left_out(name, catalog):
    found = check_parameters(parameter_set(name), catalog)
    assert original(name) != BEYOND_THE_ORIGINAL[name]
    assert [(issue.level, issue.where) for issue in found] == BEYOND_THE_ORIGINAL[name]


@pytest.mark.parametrize("name", REFUSED_BY_THE_CONTRACT)
def test_contract_refuses_what_the_original_reported(name):
    assert original(name) == REFUSED_BY_THE_CONTRACT[name]
    with pytest.raises(ValidationError):
        ParameterSet.model_validate(load(name)["parameter_set"])
