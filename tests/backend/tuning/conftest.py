from pathlib import Path

import pytest

from src.backend.infrastructure.catalog import load_catalog, load_requirement_keys
from src.backend.tuning.select import select_parameters


@pytest.fixture(scope="session")
def catalog():
    return load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")


@pytest.fixture(scope="session")
def keys():
    return load_requirement_keys(Path("knowledge/requirement_keys.json"))


@pytest.fixture
def select(catalog, keys):
    """select(card, feedback=None) -> the published parameter set."""

    def run(card, feedback=None):
        return select_parameters(card, catalog, keys, feedback).published()

    return run
