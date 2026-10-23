"""Analytical fixtures verify geometry, defects and units independently of STL names."""

import numpy as np
import pytest
import trimesh

from src.mesh_analysis import analyze_stl


def save(tmp_path, mesh, name="shape.stl"):
    path = tmp_path / name
    mesh.export(path)
    return path


def test_box_measurements_and_no_mutation(tmp_path):
    path = save(tmp_path, trimesh.creation.box(extents=[2, 3, 4]))
    original = path.read_bytes()
    report = analyze_stl(path, units="mm", samples=32)
    assert report["status"] == "checks_passed"
    assert report["geometry"]["extents"] == pytest.approx([2, 3, 4])
    assert report["geometry"]["surface_area"] == pytest.approx(52)
    assert report["geometry"]["volume"] == pytest.approx(24)
    assert report["topology"]["boundary_edges"] == 0
    assert report["topology"]["components"][0]["genus"] == 0
    assert path.read_bytes() == original
    assert report["normal_chords"]["minimum_sampled"] >= 2 - 1e-5


def test_open_mesh_does_not_claim_volume(tmp_path):
    mesh = trimesh.creation.box()
    mesh.update_faces(np.arange(len(mesh.faces) - 1))
    report = analyze_stl(save(tmp_path, mesh), samples=0)
    assert report["status"] == "issues_found"
    assert report["topology"]["boundary_edges"] == 3
    assert report["geometry"]["volume"] is None
    assert report["geometry"]["center_of_mass"] is None


def test_inverted_shell_is_reported(tmp_path):
    mesh = trimesh.creation.box()
    mesh.invert()
    report = analyze_stl(save(tmp_path, mesh), samples=0)
    assert report["status"] == "issues_found"
    assert report["topology"]["components"][0]["signed_volume"] == pytest.approx(-1)
    assert report["geometry"]["volume"] is None


def test_duplicates_and_degenerate_faces_are_not_silently_repaired(tmp_path):
    mesh = trimesh.creation.box()
    faces = np.vstack([mesh.faces, mesh.faces[0], [0, 0, 0]])
    report = analyze_stl(
        save(tmp_path, trimesh.Trimesh(mesh.vertices, faces, process=False)), samples=0
    )
    assert report["validation"]["duplicate_faces"] == 1
    assert report["validation"]["degenerate_faces"] == 1
    assert report["status"] == "issues_found"


def test_separate_components(tmp_path):
    a = trimesh.creation.box()
    b = a.copy()
    b.apply_translation([3, 0, 0])
    report = analyze_stl(save(tmp_path, a + b), samples=0)
    assert report["topology"]["component_count"] == 2
    assert report["geometry"]["volume"] is None  # nesting/intersections not resolved


def test_unit_conversion_is_explicit(tmp_path):
    path = save(tmp_path, trimesh.creation.box())
    unknown = analyze_stl(path, samples=0)
    assert unknown["units"]["coordinate_unit"] == "unknown"
    assert unknown["units"]["source"] == "not_specified"
    converted = analyze_stl(path, units="inch", samples=0)
    assert converted["geometry"]["extents"] == pytest.approx([25.4] * 3)
    assert converted["units"]["coordinate_unit"] == "mm"


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not an STL",
        b"solid x\nendsolid x\n",
        b"\0" * 80 + (5).to_bytes(4, "little"),
    ],
)
def test_malformed_files_raise_clear_error(tmp_path, payload):
    path = tmp_path / "bad.stl"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        analyze_stl(path)


def test_file_limit_before_parsing(tmp_path):
    path = save(tmp_path, trimesh.creation.box())
    with pytest.raises(ValueError, match="size"):
        analyze_stl(path, max_bytes=100)


def test_ascii_stl(tmp_path):
    path = tmp_path / "ascii.stl"
    path.write_text(trimesh.exchange.stl.export_stl_ascii(trimesh.creation.box()))
    assert analyze_stl(path, samples=0)["geometry"]["volume"] == pytest.approx(1)


def test_inconsistent_winding(tmp_path):
    mesh = trimesh.creation.box()
    mesh.faces[0] = mesh.faces[0][::-1]
    report = analyze_stl(save(tmp_path, mesh), samples=0)
    assert "inconsistent_winding" in report["validation"]["defects"]
    assert report["geometry"]["volume"] is None


def test_nonfinite_coordinates_rejected(tmp_path):
    path = save(tmp_path, trimesh.creation.box())
    import struct

    data = bytearray(path.read_bytes())
    struct.pack_into("<f", data, 96, float("nan"))
    path.write_bytes(data)
    with pytest.raises(ValueError, match="NaN"):
        analyze_stl(path)


def test_limits_and_unsupported_options(tmp_path):
    path = save(tmp_path, trimesh.creation.box())
    with pytest.raises(ValueError, match="Triangle count"):
        analyze_stl(path, max_faces=2)
    with pytest.raises(ValueError, match="units"):
        analyze_stl(path, units="yards")
    with pytest.raises(ValueError, match="samples"):
        analyze_stl(path, samples=-1)


def test_planar_single_triangle(tmp_path):
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False
    )
    report = analyze_stl(save(tmp_path, mesh), samples=0)
    assert report["geometry"]["surface_area"] == pytest.approx(0.5)
    assert report["topology"]["boundary_edges"] == 3
    assert report["topology"]["component_count"] == 1


def test_independent_binary_verifier(tmp_path):
    import runpy
    from pathlib import Path

    verify = runpy.run_path(str(Path(__file__).parent / "verify_stl_reports.py"))[
        "verify"
    ]
    path = save(tmp_path, trimesh.creation.box(extents=[2, 3, 4]))
    assert verify(analyze_stl(path, samples=0))["verified"]


def test_fully_collapsed_triangle_is_serializable(tmp_path):
    import json

    mesh = trimesh.Trimesh(vertices=[[0, 0, 0]], faces=[[0, 0, 0]], process=False)
    report = analyze_stl(save(tmp_path, mesh), samples=0)
    assert report["validation"]["degenerate_faces"] == 1
    assert report["geometry"]["surface_centroid"] is None
    json.dumps(report, allow_nan=False)
