from pathlib import Path

import pytest

from src.backend.domain.catalog import Catalog
from src.backend.infrastructure.catalog import load_catalog


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")
