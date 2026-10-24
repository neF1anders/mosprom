import json
from pathlib import Path

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.geometry import bind_analysis, summarize
from src.backend.domain.models import Attachment

pytestmark = pytest.mark.unit
REPORT = {
    "file": {"sha256": "a" * 64},
    "units": {"input_unit": "mm"},
    "geometry": {"extents": [10.0, 20.0, 30.0], "volume": None, "volume_basis": "unavailable"},
    "topology": {"component_count": 2, "watertight": False},
    "validation": {"defects": ["boundary_edges"]},
    "normal_chords": {"minimum_sampled": 1.5},
    "sections": [{"axis": "X", "fraction_of_bounds": 0.5, "coordinate": 1, "total_length": 9}],
    "warnings": ["Self-intersections are not checked."],
    "partial_errors": {"preview": "RuntimeError"},
    "preview": "k.png",
}


def stl() -> Attachment:
    return Attachment(job_id="j", filename="a.stl", kind="stl", sha256="a" * 64, size=1)


def test_summary_keeps_limits_and_does_not_invent_volume():
    geometry = summarize(REPORT, "mm", "k")
    assert geometry.readable and geometry.extents == [10.0, 20.0, 30.0]
    assert geometry.defects == ["boundary_edges", "multiple_shells"]
    assert geometry.volume is None and geometry.min_wall_sample == 1.5
    assert geometry.sections == [{"axis": "X", "fraction_of_bounds": 0.5}]
    assert "Не завершена проверка preview" in geometry.limitations
    assert (geometry.report_id, geometry.preview_id) == ("k", "k.png")


@pytest.mark.parametrize(
    "report",
    [
        {**REPORT, "file": {"sha256": "b" * 64}},
        {**REPORT, "units": {"input_unit": "unknown"}},
        {**REPORT, "file": "broken"},
    ],
)
def test_report_must_belong_to_the_active_file_and_units(report):
    with pytest.raises(AppError):
        bind_analysis(stl(), "mm", report)


def test_full_report_is_embedded_unchanged():
    report = json.loads(json.dumps(REPORT))
    assert bind_analysis(stl(), "mm", report).report == REPORT


@pytest.mark.skipif(not Path("artifacts/stl-final").exists(), reason="local analyzer reports")
def test_summary_of_real_reports():
    for path in sorted(Path("artifacts/stl-final").glob("*.json"))[:7]:
        report = json.loads(path.read_text())
        if "geometry" in report:
            assert summarize(report, "unknown", "k").readable
