import pytest
import trimesh

from src import mesh_analysis

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("operation", ["section_summary", "normal_chords"])
def test_T05_optional_failure_preserves_geometry(tmp_path, monkeypatch, operation):
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=[10, 20, 30]).export(path)

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(mesh_analysis, operation, broken)
    report = mesh_analysis.analyze_stl(path, units="mm")
    assert report["geometry"]["extents"] == [10, 20, 30]
    assert report["partial_errors"]


def test_T05_preview_failure_preserves_report(tmp_path, monkeypatch):
    from src.backend.infrastructure.process_runner import analyze

    path = tmp_path / "box.stl"
    trimesh.creation.box().export(path)

    def broken(*args, **kwargs):
        raise RuntimeError("preview")

    monkeypatch.setattr(mesh_analysis, "write_preview", broken)
    report = analyze(path, "mm", tmp_path / "report.json")
    assert report["geometry"]["extents"] == [1, 1, 1]
    assert report["partial_errors"]["preview"] == "RuntimeError"


def test_T05_shape_failure_keeps_independent_sections(tmp_path, monkeypatch):
    path = tmp_path / "box.stl"
    trimesh.creation.box().export(path)

    def broken(*args, **kwargs):
        raise RuntimeError("hull")

    monkeypatch.setattr(trimesh.Trimesh, "convex_hull", property(broken))
    report = mesh_analysis.analyze_stl(path, units="mm")
    assert report["geometry"]["extents"] == [1, 1, 1]
    assert report["sections"]
    assert report["partial_errors"]["shape"] == "RuntimeError"


@pytest.mark.parametrize("failure", ["timeout", "crash"])
async def test_T05_checkpoint_survives_process_exit(tmp_path, monkeypatch, failure):
    import asyncio
    import json

    from src.backend.infrastructure.files import LocalFiles

    files = LocalFiles(tmp_path, timeout=0.001)
    (tmp_path / "result.json").write_text(json.dumps({"geometry": {"extents": [1, 2, 3]}}))

    class Process:
        returncode = 1
        killed = False

        async def wait(self):
            if failure == "timeout" and not self.killed:
                await asyncio.sleep(10)

        def kill(self):
            self.killed = True

    async def start(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    report = await files.analyze("input", "unknown", "result")
    assert report["geometry"]["extents"] == [1, 2, 3]
    assert report["status"] == "partial"
    assert report["partial_errors"]["process"] == (
        "timeout" if failure == "timeout" else "process_crash"
    )
