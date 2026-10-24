"""Analytical fixtures verify geometry, defects and units independently of STL names."""

import time

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


def tube():
    return trimesh.creation.annulus(r_min=5, r_max=10, height=30)


def test_tube_is_a_revolution_with_a_through_bore(tmp_path):
    report = analyze_stl(save(tmp_path, tube()), units="mm", samples=0)
    revolution = report["revolution"]
    assert revolution["is_revolution"] and revolution["round_fraction"] == 1
    assert np.abs(revolution["axis_direction"]) == pytest.approx([0, 0, 1], abs=1e-3)
    assert revolution["bore"]["through"]
    assert revolution["bore"]["diameter_mm"] == pytest.approx(10, abs=0.2)
    assert revolution["outer_diameter_mm"] == pytest.approx(20, abs=0.2)
    assert revolution["length_along_axis_mm"] == pytest.approx(30)


def test_open_tube_is_still_a_revolution(tmp_path):
    mesh = tube()
    mesh.update_faces(np.abs(mesh.face_normals[:, 2]) < 0.5)  # drop both caps
    mesh.remove_unreferenced_vertices()
    report = analyze_stl(save(tmp_path, mesh), units="mm", samples=0)
    assert "boundary_edges" in report["validation"]["defects"]
    assert report["revolution"]["is_revolution"]
    assert report["revolution"]["bore"]["diameter_mm"] == pytest.approx(10, abs=0.2)


def test_bore_of_a_lopsided_tube_is_measured_around_its_axis(tmp_path):
    # The lug pulls the surface centroid 3.4 mm off the axis, inside the 5 mm bore.
    lug = trimesh.creation.box(extents=(20, 8, 10))
    lug.apply_translation((20, 0, -15))
    mesh = trimesh.util.concatenate([trimesh.creation.annulus(r_min=5, r_max=10, height=40), lug])
    report = analyze_stl(save(tmp_path, mesh), units="mm", samples=0)
    revolution = report["revolution"]
    assert revolution["is_revolution"] and revolution["bore"]["through"]
    assert revolution["axis_point"][:2] == pytest.approx([0, 0], abs=0.01)
    assert revolution["bore"]["diameter_mm"] == pytest.approx(10, abs=0.2)


def test_many_separate_shells_are_analysed_in_bounded_time(tmp_path):
    cubes = []
    for i in range(20):
        for j in range(20):
            cube = trimesh.creation.box(extents=(1, 1, 1))
            cube.apply_translation((2 * i, 2 * j, 0))
            cubes.append(cube)
    path = save(tmp_path, trimesh.util.concatenate(cubes))
    started = time.perf_counter()
    report = analyze_stl(path, units="mm", samples=0)
    # Every belt cuts 400 loops; comparing each with each took about a minute.
    assert time.perf_counter() - started < 20
    assert report["revolution"]["is_revolution"] is False


def chamfered(offset):
    """A bar whose underside edge is cut at exactly 45 degrees, from (y, z) = (0, 5) to (5, 0)."""
    section = [(0, 5), (5, 0), (20, 0), (20, 10), (0, 10)]
    n = len(section)
    vertices = np.array([(x, y, z) for x in (0.0, 10.0) for y, z in section]) + offset
    faces = [
        face
        for i in range(n)
        for face in ((i, (i + 1) % n, n + (i + 1) % n), (i, n + (i + 1) % n, n + i))
    ]
    faces += [face for k in range(1, n - 1) for face in ((0, k + 1, k), (n, n + k, n + k + 1))]
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def test_a_45_degree_chamfer_is_not_an_overhang_wherever_the_part_sits(tmp_path):
    rng = np.random.default_rng(2)
    fractions = {
        analyze_stl(save(tmp_path, chamfered(offset)), samples=0)["overhangs"]["area_fraction"]
        for offset in [np.zeros(3), *rng.uniform(-900, 900, (20, 3))]
    }
    assert fractions == {0}


def test_overhangs_reach_the_checkpoint_before_the_slow_sections(tmp_path, monkeypatch):
    import src.mesh_analysis as analysis

    checkpoints = []

    def cut(mesh):
        # What the parent keeps when the time limit kills the process here.
        raise KeyboardInterrupt

    monkeypatch.setattr(analysis, "revolution", cut)
    with pytest.raises(KeyboardInterrupt):
        analyze_stl(save(tmp_path, tube()), samples=0, checkpoint=checkpoints.append)
    assert checkpoints[-1]["status"] == "partial"
    assert checkpoints[-1]["overhangs"]["critical_angle_deg"] == 45


def test_box_bottom_rests_on_the_bed(tmp_path):
    report = analyze_stl(save(tmp_path, trimesh.creation.box(extents=[10, 20, 30])), samples=0)
    assert report["overhangs"]["area_mm2"] == 0
    assert report["overhangs"]["bed_contact_area_mm2"] == pytest.approx(200)
    assert report["overhangs"]["critical_angle_deg"] == 45
    assert report["revolution"]["is_revolution"] is False
    assert report["revolution"]["bore"] is None
    assert report["revolution"]["wall_to_radius"] == 1


def test_wide_plate_on_a_post_overhangs_outside_the_bed_band(tmp_path):
    post = trimesh.creation.box(extents=[10, 10, 10])
    post.apply_translation([0, 0, 5])
    plate = trimesh.creation.box(extents=[30, 30, 5])
    plate.apply_translation([0, 0, 12.5])
    report = analyze_stl(save(tmp_path, post + plate), units="mm", samples=0)
    overhangs = report["overhangs"]
    assert overhangs["area_mm2"] == pytest.approx(900)
    assert overhangs["bed_contact_area_mm2"] == pytest.approx(100)
    assert overhangs["area_fraction"] == pytest.approx(
        900 / report["geometry"]["surface_area"], abs=1e-4
    )


def test_orientations_start_as_loaded_and_are_rotations(tmp_path):
    # Tilted, so standing on the axis is not one of the axis-aligned candidates.
    mesh = tube()
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(30), [1, 0, 0]))
    report = analyze_stl(save(tmp_path, mesh), units="mm", samples=0)
    candidates = report["orientations"]
    assert 1 <= len(candidates) <= 12
    assert [c["id"] for c in candidates] == [f"o{i}" for i in range(1, len(candidates) + 1)]
    assert candidates[0]["source"] == "as_loaded"
    assert candidates[0]["rotation"] == np.eye(3).tolist()
    assert candidates[0]["overhang_area_mm2"] == report["overhangs"]["area_mm2"]
    for candidate in candidates:
        rotation = np.array(candidate["rotation"])
        assert rotation @ rotation.T == pytest.approx(np.eye(3), abs=1e-5)
        assert np.linalg.det(rotation) == pytest.approx(1, abs=1e-5)
    assert "revolution_axis" in {c["source"] for c in candidates}


def test_failed_revolution_is_null_and_named(tmp_path, monkeypatch):
    import src.mesh_analysis as analysis

    def broken(mesh):
        raise RuntimeError

    monkeypatch.setattr(analysis, "revolution", broken)
    report = analyze_stl(save(tmp_path, tube()), samples=0)
    assert report["revolution"] is None
    assert report["partial_errors"] == {"revolution": "RuntimeError"}
    assert report["orientations"][0]["source"] == "as_loaded"
    assert "overhangs" in report


def test_new_sections_follow_the_stage_two_contract(tmp_path):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    report = analyze_stl(save(tmp_path, tube()), units="mm", samples=0)
    json.dumps(report, allow_nan=False)
    assert report["schema_version"] == "1.2"
    contract = json.loads(Path("docs/stage1-contract.schema.json").read_text())
    schema = {"$defs": contract["$defs"], **contract["$defs"]["StlReport"]}
    Draft202012Validator(schema).validate(report)
