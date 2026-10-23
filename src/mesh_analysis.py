"""Read-only STL inspection. Run with Python 3.10+, independently of STE Slicer.

All lengths use report['units']['coordinate_unit']; no material or print profile
is inferred from geometry. A passed check is not certification of printability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_FACES = 2_000_000


def statistics(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values)
    if not len(values):
        return {"count": 0}
    return {
        "count": len(values),
        "min": float(values.min()),
        "p05": float(np.percentile(values, 5)),
        "median": float(np.median(values)),
        "mean": float(values.mean()),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
    }


def read_stl(
    path: Path, max_bytes: int, max_faces: int
) -> tuple[trimesh.Trimesh, dict]:
    """Preflight size/counts before parsing; preserve all faces and coordinates."""
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"File size {size} exceeds limit {max_bytes}")
    if size < 15:
        raise ValueError("Empty or truncated STL")
    data = path.read_bytes()
    declared = struct.unpack_from("<I", data, 80)[0] if size >= 84 else 0
    binary = size >= 84 and 84 + 50 * declared == size
    if binary:
        count = declared
        encoding = "binary"
    else:
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "Invalid STL: binary length/count mismatch or non-ASCII text"
            ) from exc
        if "\x00" in text or not text.lstrip().lower().startswith("solid"):
            raise ValueError("Invalid STL header or truncated binary STL")
        count = len(re.findall(r"(?m)^\s*facet\s+normal\s", text, re.I))
        vertices = len(re.findall(r"(?m)^\s*vertex\s", text, re.I))
        ends = len(re.findall(r"(?m)^\s*endfacet\s*$", text, re.I))
        if (
            vertices != 3 * count
            or ends != count
            or not re.search(r"(?m)^\s*endsolid\b", text, re.I)
        ):
            raise ValueError("Incomplete or malformed ASCII STL facets")
        encoding = "ascii"
    if count == 0 or count > max_faces:
        raise ValueError(f"Triangle count {count} is outside limit 1..{max_faces}")
    with path.open("rb") as stream:
        mesh = trimesh.load_mesh(stream, file_type="stl", process=False)
    if len(mesh.faces) != count:
        raise ValueError("Parser triangle count differs from preflight count")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("STL contains NaN or infinite coordinates")
    return mesh, {
        "encoding": encoding,
        "bytes": size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "triangles": count,
    }


def normal_chords(mesh: trimesh.Trimesh, samples: int) -> dict:
    """Deterministic area-weighted surface samples; inward normal first exit.

    These are chords, NOT a minimum wall-thickness proof or local feature size.
    """
    rng = np.random.default_rng(0)
    face_ids = rng.choice(len(mesh.faces), samples, p=mesh.area_faces / mesh.area)
    triangles = mesh.triangles[face_ids]
    uv = rng.random((samples, 2))
    uv[uv.sum(axis=1) > 1] = 1 - uv[uv.sum(axis=1) > 1]
    starts = (
        triangles[:, 0]
        + uv[:, :1] * (triangles[:, 1] - triangles[:, 0])
        + uv[:, 1:] * (triangles[:, 2] - triangles[:, 0])
    )
    directions = -mesh.face_normals[face_ids]
    epsilon = max(float(np.linalg.norm(mesh.extents)) * 1e-8, np.finfo(float).eps)
    origins = starts + directions * epsilon
    hits, rays, _ = mesh.ray.intersects_location(
        origins, directions, multiple_hits=False
    )
    lengths = np.linalg.norm(hits - starts[rays], axis=1)
    accepted = lengths > epsilon * 2
    hits, rays, lengths = hits[accepted], rays[accepted], lengths[accepted]
    shortest = np.argsort(lengths)[:10]
    return {
        "status": "estimated",
        "requested_samples": samples,
        "seed": 0,
        "method": "area_weighted_surface_inward_normal_first_exit",
        "minimum_sampled": float(lengths.min()) if len(lengths) else None,
        "distribution": statistics(lengths),
        "missed_or_too_close": samples - len(lengths),
        "shortest_samples": [
            {
                "length": float(lengths[i]),
                "face_index": int(face_ids[rays[i]]),
                "surface_point": starts[rays[i]].tolist(),
                "exit_point": hits[i].tolist(),
            }
            for i in shortest
        ],
        "limitations": "Not true minimum wall thickness; can miss small thin features. Concavities, cavities and grazing rays affect results.",
    }


def section_summary(mesh: trimesh.Trimesh) -> list[dict]:
    result = []
    for axis in range(3):
        for fraction in (0.25, 0.5, 0.75):
            origin = mesh.bounds.mean(axis=0)
            origin[axis] = mesh.bounds[0, axis] + mesh.extents[axis] * fraction
            normal = np.eye(3)[axis]
            section = mesh.section(plane_origin=origin, plane_normal=normal)
            record = {
                "axis": "XYZ"[axis],
                "fraction_of_bounds": fraction,
                "coordinate": float(origin[axis]),
                "closed_contour_count": 0,
                "open_entity_count": 0,
                "total_length": 0.0,
            }
            if section is not None:
                curves = section.discrete
                closed = [
                    c
                    for c in curves
                    if len(c) > 2
                    and np.allclose(
                        c[0], c[-1], rtol=0, atol=max(mesh.extents.max() * 1e-8, 1e-12)
                    )
                ]
                record.update(
                    closed_contour_count=len(closed),
                    open_entity_count=len(section.dangling),
                    total_length=float(section.length),
                )
            result.append(record)
    return result


def analyze_stl(
    path: Path | str,
    *,
    units: str = "unknown",
    samples: int = 128,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_faces: int = DEFAULT_MAX_FACES,
    checkpoint: Callable[[dict], None] | None = None,
) -> dict:
    """Return JSON-serializable observations without modifying the input file."""
    started = time.perf_counter()
    path = Path(path).resolve()
    if units not in {"unknown", "mm", "cm", "m", "inch"}:
        raise ValueError("Unsupported units")
    if not 0 <= samples <= 4096:
        raise ValueError("samples must be between 0 and 4096")
    raw, file_info = read_stl(path, max_bytes, max_faces)
    scale = {"unknown": 1, "mm": 1, "cm": 10, "m": 1000, "inch": 25.4}[units]
    # Exact welding only: STL repeats vertices; do not round or repair the mesh.
    vertices, inverse = np.unique(raw.vertices * scale, axis=0, return_inverse=True)
    faces = inverse[raw.faces]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if checkpoint:
        checkpoint({
            "schema_version": "1.1", "status": "partial",
            "file": {"path": str(path), **file_info},
            "geometry": {"bounds": mesh.bounds.tolist(), "extents": mesh.extents.tolist(), "volume": None},
            "units": {"input_unit": units, "coordinate_unit": "unknown" if units == "unknown" else "mm"},
            "validation": {"defects": ["topology_unchecked"]},
            "warnings": ["Topology has not completed; physical volume is unavailable."],
        })
    diagonal = float(np.linalg.norm(mesh.extents))
    area_tolerance = max(diagonal**2 * 1e-14, np.finfo(float).tiny)
    areas = mesh.area_faces
    degenerates = areas <= area_tolerance
    canonical = np.sort(faces, axis=1)
    duplicate_count = len(faces) - len(np.unique(canonical, axis=0))
    edges, edge_counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    boundary = edges[edge_counts == 1]
    nonmanifold = edges[edge_counts > 2]
    components = mesh.split(only_watertight=False, repair=False)
    parts = []
    for part in components:
        closed = bool(part.is_watertight)
        winding = bool(part.is_winding_consistent)
        chi = int(part.euler_number)
        parts.append(
            {
                "faces": len(part.faces),
                "vertices": len(part.vertices),
                "bounds": part.bounds.tolist(),
                "surface_area": float(part.area),
                "watertight": closed,
                "winding_consistent": winding,
                "euler_number": chi,
                "genus": (2 - chi) // 2
                if closed and winding and (2 - chi) % 2 == 0 and chi <= 2
                else None,
                "signed_volume": float(part.volume) if closed and winding else None,
            }
        )
    parts.sort(key=lambda p: p["faces"], reverse=True)
    defects = []
    if degenerates.any():
        defects.append("degenerate_faces")
    if duplicate_count:
        defects.append("duplicate_faces")
    if len(boundary):
        defects.append("boundary_edges")
    if len(nonmanifold):
        defects.append("nonmanifold_edges")
    if not mesh.is_winding_consistent:
        defects.append("inconsistent_winding")
    if any(p["signed_volume"] is not None and p["signed_volume"] <= 0 for p in parts):
        defects.append("nonpositive_shell_volume")
    volume_eligible = not defects and len(parts) == 1 and mesh.is_volume
    warnings = [
        "Self-intersections and intersections/nesting between shells are not checked.",
        "STL does not encode authoritative units; the supplied unit is an explicit caller assumption.",
        "Geometry does not establish material, load capacity, tolerances, manufacturing accuracy or printability.",
    ]
    if len(parts) > 1:
        warnings.append(
            "Multiple connected shells: separate parts, nested cavities or overlaps require further analysis; combined physical volume withheld."
        )
    geometry = {
        "bounds": mesh.bounds.tolist(),
        "extents": mesh.extents.tolist(),
        "bounds_center": mesh.bounds.mean(axis=0).tolist(),
        "surface_centroid": mesh.centroid.tolist() if mesh.area > 0 else None,
        "surface_area": float(mesh.area),
        "volume": float(mesh.volume) if volume_eligible else None,
        "volume_basis": "closed_single_shell_positive_winding; conditional on no self-intersections"
        if volume_eligible
        else "unavailable_for_this_topology",
        "center_of_mass": mesh.center_mass.tolist() if volume_eligible else None,
        "inertia_unit_density": mesh.moment_inertia.tolist()
        if volume_eligible
        else None,
        "aabb_volume": float(np.prod(mesh.extents)),
        "edge_lengths": statistics(mesh.edges_unique_length),
        "triangle_areas": statistics(areas),
        "triangle_min_angles_degrees": statistics(
            np.degrees(mesh.face_angles.min(axis=1))
        ),
        "adjacent_face_angles_degrees": statistics(
            np.degrees(mesh.face_adjacency_angles)
        ),
    }
    partial_errors = {}
    base_checkpoint = {
        "schema_version": "1.1", "status": "partial",
        "file": {"path": str(path), **file_info},
        "geometry": geometry, "validation": {"defects": defects},
        "units": {"input_unit": units, "coordinate_unit": "unknown" if units == "unknown" else "mm"},
        "topology": {"component_count": len(parts)},
        "warnings": warnings, "partial_errors": partial_errors,
    }
    if checkpoint:
        checkpoint(base_checkpoint)
    try:
        # Convex hull and PCA describe shape, not the semantic identity of the part.
        if (
            len(vertices) >= 4
            and np.linalg.matrix_rank(vertices - vertices.mean(axis=0)) == 3
        ):
            hull = mesh.convex_hull
            covariance = np.cov((vertices - vertices.mean(axis=0)).T)
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            order = np.argsort(eigenvalues)[::-1]
            axes = eigenvectors[:, order]
            projections = vertices @ axes
            geometry.update(
                convex_hull_volume=float(hull.volume),
                convex_hull_area=float(hull.area),
                volume_to_convex_hull_ratio=float(mesh.volume / hull.volume)
                if volume_eligible
                else None,
                vertex_pca={
                    "axes_columns": axes.tolist(),
                    "eigenvalues": eigenvalues[order].tolist(),
                    "extents_in_pca_frame": np.ptp(projections, axis=0).tolist(),
                    "method": "vertex_weighted; depends_on_tessellation; not_minimum_oriented_box",
                },
            )
    except Exception as exc:
        partial_errors["shape"] = type(exc).__name__
    chord_report = {
        "status": "not_run",
        "reason": "disabled"
        if samples == 0
        else "requires one closed, consistently oriented, defect-free shell",
    }
    if samples and volume_eligible:
        try:
            chord_report = normal_chords(mesh, samples)
        except Exception as exc:  # independent optional measurement boundary
            partial_errors["normal_chords"] = type(exc).__name__
            chord_report = {"status": "error", "reason": type(exc).__name__}
    try:
        sections = section_summary(mesh)
    except Exception as exc:  # preserve validated geometry on section failure
        partial_errors["sections"] = type(exc).__name__
        sections = []
    report = {
        "schema_version": "1.0",
        "status": "issues_found" if defects else "checks_passed",
        "status_scope": "listed mesh checks only; self-intersections and printability are unverified",
        "file": {"path": str(path), **file_info},
        "software": {"trimesh": trimesh.__version__, "numpy": np.__version__},
        "units": {
            "input_unit": units,
            "coordinate_unit": "unknown" if units == "unknown" else "mm",
            "source": "not_specified" if units == "unknown" else "caller_supplied",
            "scale_applied": scale,
            "area_unit": "coordinate_unit^2",
            "volume_unit": "coordinate_unit^3",
        },
        "preprocessing": {
            "exact_duplicate_vertices_welded": len(raw.vertices) - len(vertices),
            "faces_removed": 0,
            "repair_performed": False,
            "area_degeneracy_threshold": area_tolerance,
        },
        "validation": {
            "defects": defects,
            "finite_coordinates": True,
            "degenerate_faces": int(degenerates.sum()),
            "duplicate_faces": duplicate_count,
            "self_intersections": "not_checked",
            "shell_intersections_and_nesting": "not_checked",
            "vertex_manifoldness": "not_checked",
        },
        "topology": {
            "vertices_after_exact_weld": len(vertices),
            "unique_edges": len(edges),
            "boundary_edges": len(boundary),
            "nonmanifold_edges": len(nonmanifold),
            "boundary_edge_examples": boundary[:20].tolist(),
            "nonmanifold_edge_examples": nonmanifold[:20].tolist(),
            "watertight": bool(mesh.is_watertight),
            "winding_consistent": bool(mesh.is_winding_consistent),
            "euler_number": int(mesh.euler_number),
            "component_count": len(parts),
            "components": parts,
        },
        "geometry": geometry,
        "sections": sections,
        "partial_errors": partial_errors,
        "normal_chords": chord_report,
        "warnings": warnings,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }
    if checkpoint:
        checkpoint(report)
    return report


def write_preview(path: Path, destination: Path) -> None:
    """Orthographic surface projections; visual aid, never a measurement source."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    mesh = trimesh.load_mesh(path, file_type="stl", process=False)
    fig, panels = plt.subplots(1, 3, figsize=(15, 5))
    # Painter ordering keeps this renderer usable without OpenGL/display drivers.
    for panel, (a, b, depth) in zip(panels, [(0, 1, 2), (0, 2, 1), (1, 2, 0)]):
        order = np.argsort(mesh.triangles_center[:, depth])
        shade = 0.35 + 0.55 * np.abs(mesh.face_normals[order, depth])
        colors = np.column_stack(
            [shade * 0.5, shade * 0.75, shade, np.ones(len(shade))]
        )
        panel.add_collection(
            PolyCollection(
                mesh.triangles[order][:, :, [a, b]],
                facecolors=colors,
                edgecolors="none",
                rasterized=True,
            )
        )
        panel.autoscale_view()
        panel.set_aspect("equal")
        panel.set_xlabel("XYZ"[a] + " (file units)")
        panel.set_ylabel("XYZ"[b] + " (file units)")
        panel.set_title("XYZ"[a] + "XYZ"[b])
    fig.tight_layout()
    fig.savefig(destination, dpi=120)
    plt.close(fig)


def markdown_report(report: dict) -> str:
    title = Path(report["file"]["path"]).name
    if report["status"] == "error":
        return f"# {title}\n\nОшибка анализа: {report['error']}\n"
    g, t, v = report["geometry"], report["topology"], report["validation"]
    text = [
        f"# {title}",
        "",
        f"Статус: **{report['status']}** — только перечисленные проверки сетки.",
        "",
        f"Единицы координат: `{report['units']['coordinate_unit']}`; источник: `{report['units']['source']}`.",
        f"Габариты XYZ: {g['extents']}",
        f"Треугольников: {report['file']['triangles']}; вершин после точного объединения: {t['vertices_after_exact_weld']}",
        f"Площадь поверхности: {g['surface_area']}",
        f"Условный объём: {g['volume']}; основание: {g['volume_basis']}",
        f"Связных оболочек: {t['component_count']}",
        f"Замкнута: {t['watertight']}; согласованность обхода: {t['winding_consistent']}",
        f"Граничных рёбер: {t['boundary_edges']}; неманифолдных рёбер: {t['nonmanifold_edges']}",
        f"Дубликатов граней: {v['duplicate_faces']}; вырожденных граней: {v['degenerate_faces']}",
        f"Дефекты: {', '.join(v['defects']) or 'не обнаружены перечисленными проверками'}",
        "",
        "## Выборочная оценка хорд",
        "",
        json.dumps(report["normal_chords"], ensure_ascii=False, indent=2),
        "",
        "## Ограничения",
        "",
    ]
    text.extend(f"- {warning}" for warning in report["warnings"])
    text.extend(
        [
            "",
            "Полные измерения, статистика, оболочки, PCA и девять сечений доступны в соседнем JSON.",
            "",
        ]
    )
    return "\n".join(text)


def main() -> int:
    # Use a single encoding for worker pipes and Unicode model names on Windows.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs", nargs="+", type=Path, help="STL files or directories (recursive)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/stl-analysis")
    )
    parser.add_argument(
        "--units", choices=["unknown", "mm", "cm", "m", "inch"], default="unknown"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=128,
        help="Normal chord samples (0 disables, max 4096)",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-faces", type=int, default=DEFAULT_MAX_FACES)
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="Seconds per file, enforced by parent process",
    )
    parser.add_argument(
        "--preview", action="store_true", help="Write orthographic PNG previews"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (
        not 0 <= args.samples <= 4096
        or min(args.max_bytes, args.max_faces, args.timeout) <= 0
    ):
        parser.error("Invalid resource limits or samples (expected 0..4096)")
    if args.worker:
        try:
            report = analyze_stl(
                args.inputs[0],
                units=args.units,
                samples=args.samples,
                max_bytes=args.max_bytes,
                max_faces=args.max_faces,
            )
            if args.preview:
                try:
                    write_preview(args.inputs[0], args.output_dir)
                except Exception as exc:
                    report.setdefault("partial_errors", {})["preview"] = type(exc).__name__
        except Exception as exc:  # process boundary: convert failures into explicit machine-readable errors
            report = {
                "schema_version": "1.0",
                "status": "error",
                "file": {"path": str(args.inputs[0].resolve())},
                "error": f"{type(exc).__name__}: {exc}",
            }
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        return 0
    files = set()
    for entry in args.inputs:
        if entry.is_dir():
            files.update(
                p.resolve()
                for p in entry.rglob("*")
                if p.is_file() and p.suffix.lower() == ".stl"
            )
        else:
            files.add(entry.resolve())
    if not files:
        parser.error("No STL files found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for number, path in enumerate(sorted(files), 1):
        stem = f"{number:02d}_{hashlib.sha256(str(path).encode()).hexdigest()[:10]}"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(path),
            "--worker",
            "--units",
            args.units,
            "--samples",
            str(args.samples),
            "--max-bytes",
            str(args.max_bytes),
            "--max-faces",
            str(args.max_faces),
        ]
        if args.preview:
            command.extend(
                [
                    "--preview",
                    "--output-dir",
                    str((args.output_dir / (stem + ".png")).resolve()),
                ]
            )
        try:
            run = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=args.timeout,
                check=True,
            )
            report = json.loads(run.stdout)
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
        ) as exc:
            report = {
                "schema_version": "1.0",
                "status": "error",
                "file": {"path": str(path)},
                "error": f"{type(exc).__name__}: analysis failed or timed out",
            }
        (args.output_dir / (stem + ".json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (args.output_dir / (stem + ".md")).write_text(
            markdown_report(report), encoding="utf-8"
        )
        index.append(
            {
                "file": str(path),
                "status": report["status"],
                "json": stem + ".json",
                "markdown": stem + ".md",
            }
        )
        print(f"{report['status']}: {path.name}", flush=True)
    (args.output_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return int(any(r["status"] != "checks_passed" for r in index))


if __name__ == "__main__":
    raise SystemExit(main())
