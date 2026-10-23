import pytest

from stl_factory import cube, frustum, write_ascii, write_binary
from tuning.geometry import StlError, extract_features


def test_cube_features(tmp_path):
    path = tmp_path / "cube.stl"
    write_binary(path, cube(10))
    features = extract_features(str(path))
    assert features["triangle_count"] == 12
    assert features["bbox_mm"]["size"] == [10.0, 10.0, 10.0]
    assert features["volume_mm3"] == pytest.approx(1000.0)
    assert features["surface_area_mm2"] == pytest.approx(600.0)
    assert features["is_closed"] and features["normals_consistent"]
    assert not features["needs_repair"]
    assert features["overhang_area_fraction"] == 0.0
    assert features["min_wall_estimate_mm"] == pytest.approx(3.333, abs=1e-3)


def test_ascii_and_binary_agree(tmp_path):
    write_binary(tmp_path / "b.stl", cube(7))
    write_ascii(tmp_path / "a.stl", cube(7))
    assert extract_features(str(tmp_path / "a.stl")) == extract_features(str(tmp_path / "b.stl"))


def test_binary_file_with_solid_header_is_read_as_binary(tmp_path):
    path = tmp_path / "solid_header.stl"
    write_binary(path, cube(5), header=b"solid exported by cad")
    assert extract_features(str(path))["triangle_count"] == 12


def test_missing_face_marks_mesh_open(tmp_path):
    path = tmp_path / "open.stl"
    write_binary(path, cube(10)[:-1])
    features = extract_features(str(path))
    assert not features["is_closed"]
    assert features["needs_repair"]


def test_flipped_face_marks_normals_inconsistent(tmp_path):
    triangles = cube(10)
    a, b, c = triangles[0]
    triangles[0] = (a, c, b)
    path = tmp_path / "flipped.stl"
    write_binary(path, triangles)
    features = extract_features(str(path))
    assert not features["normals_consistent"]
    assert features["needs_repair"]


def test_wide_top_has_overhang_and_bed_face_is_not_counted(tmp_path):
    path = tmp_path / "mushroom.stl"
    write_binary(path, frustum(5, 15, 5))
    features = extract_features(str(path))
    # Slanted side (~702 mm2) of ~1488 mm2 total; counting the bed-side cap would give ~0.52.
    assert features["overhang_area_fraction"] == pytest.approx(0.47, abs=0.02)
    assert features["is_closed"] and features["normals_consistent"]


def test_straight_cylinder_has_no_overhang(tmp_path):
    path = tmp_path / "cylinder.stl"
    write_binary(path, frustum(10, 10, 20))
    assert extract_features(str(path))["overhang_area_fraction"] == 0.0


def test_garbage_file_is_rejected(tmp_path):
    path = tmp_path / "garbage.stl"
    path.write_bytes(b"this is not a mesh")
    with pytest.raises(StlError):
        extract_features(str(path))
