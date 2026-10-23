from uuid import uuid4

import pytest

from src.backend.domain.models import Attachment
from src.backend.services.geometry import GeometryService

pytestmark = pytest.mark.integration


class CountingAnalyzer:
    def __init__(self):
        self.calls = 0

    async def analyze(self, key, units, cache_key):
        self.calls += 1
        return {"geometry": {"extents": [10, 20, 30]}, "topology": {"component_count": 1}}


@pytest.mark.parametrize("change", ["same", "same_content_new_id", "units", "algorithm", "content"])
async def test_T09_A04_geometry_cache_identity(pg, monkeypatch, change):
    analyzer = CountingAnalyzer()
    geometry = GeometryService(pg.uow, analyzer)
    attachment = Attachment(
        job_id=str(uuid4()), filename="box.stl", kind="stl", sha256="a" * 64, size=100
    )
    first = await geometry.analyze(attachment, "mm")
    units = "mm"
    if change == "same_content_new_id":
        attachment.id = str(uuid4())
    if change == "units":
        units = "cm"
    if change == "algorithm":
        monkeypatch.setattr("src.backend.services.geometry.ANALYZER_VERSION", "test-new-algorithm")
    if change == "content":
        attachment.sha256 = "b" * 64
    second = await geometry.analyze(attachment, units)
    expected_cached = change in {"same", "same_content_new_id"}
    assert not first[2]
    assert second[2] == expected_cached
    assert analyzer.calls == (1 if expected_cached else 2)
