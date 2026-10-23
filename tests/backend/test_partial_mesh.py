import pytest
import trimesh
from src import mesh_analysis

pytestmark = pytest.mark.unit


@pytest.mark.parametrize('operation', ['section_summary', 'normal_chords'])
def test_T05_optional_failure_preserves_geometry(tmp_path, monkeypatch, operation):
    path = tmp_path / 'box.stl'
    trimesh.creation.box(extents=[10,20,30]).export(path)
    def broken(*args, **kwargs):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(mesh_analysis, operation, broken)
    report = mesh_analysis.analyze_stl(path, units='mm')
    assert report['geometry']['extents'] == [10,20,30]
    assert report['partial_errors']
