"""Read-only STL inspection. Run with Python 3.10+, independently of STE Slicer.

All lengths use report['units']['coordinate_unit']; no material or print profile
is inferred from geometry. A passed check is not certification of printability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
# Shared with stage 2 rules (docs/stage1-contract.schema.json), so a 0.05 overhang
# threshold means the same on both sides.
OVERHANG_ANGLE = 45  # degrees from vertical
# A normal this close to the limit counts as on it: the float32 coordinates of STL leave a
# 45 degree chamfer either side of sin 45 depending on where the part sits in the file.
LIMIT_TOLERANCE = 1e-4
BED_BAND = 0.2
BELTS, SECTORS = 24, 36
ROUND_CV = 0.03  # radius variation below which a belt counts as round
PAIRS = 1 << 22  # points x edges compared at once in the loop tests
DOWN, UP = np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])


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


def _finite(value: Any, digits: int) -> float | None:
    """Rounded plain float, None for NaN/inf: checkpoints are dumped with allow_nan=False."""
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, digits) + 0.0  # + 0.0 turns -0.0 into 0.0


def _vector(values: Any, digits: int) -> list[float] | None:
    result = [_finite(v, digits) for v in values]
    return None if None in result else result


def _present(record: dict, keep: tuple[str, ...] = ()) -> dict:
    # The contract types numbers as plain numbers: a missing value is omitted, not null.
    return {k: v for k, v in record.items() if v is not None or k in keep}


def overhang_stats(mesh: trimesh.Trimesh, rotation: np.ndarray) -> dict:
    """Down-facing faces beyond 45 degrees from vertical after the rotation.

    Dropping the model onto the bed is a translation and does not change them.
    """
    up = rotation[2]  # rotated z in STL coordinates
    normal_z = mesh.face_normals @ up
    face_z = (mesh.vertices @ up)[mesh.faces]
    # Faces wholly inside the band rest on the bed and need no support.
    in_band = face_z.max(axis=1) <= face_z.min() + BED_BAND
    areas = mesh.area_faces
    over = (normal_z < -math.sin(math.radians(OVERHANG_ANGLE)) - LIMIT_TOLERANCE) & ~in_band
    area, total = float(areas[over].sum()), float(mesh.area)
    extents = np.ptp(mesh.vertices @ rotation.T, axis=0)
    return {
        "area_mm2": _finite(area, 1),
        "area_fraction": _finite(area / total, 4) if total > 0 else 0.0,
        "bed_contact_area_mm2": _finite(areas[in_band & (normal_z < -0.98)].sum(), 1),
        "height_mm": _finite(extents[2], 2),
        "extents_mm": _vector(extents, 2),
    }


def overhangs(mesh: trimesh.Trimesh) -> dict:
    stats = overhang_stats(mesh, np.eye(3))
    return _present({
        "critical_angle_deg": OVERHANG_ANGLE,
        "bed_band_mm": BED_BAND,
        "area_mm2": stats["area_mm2"],
        "area_fraction": stats["area_fraction"],
        "bed_contact_area_mm2": stats["bed_contact_area_mm2"],
        "method": (
            f"face_normals_as_loaded; n_z_below_minus_sin45_by_{LIMIT_TOLERANCE:g}; "
            "faces_within_bed_band_excluded"
        ),
    })


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation taking direction a onto direction b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if c < -1 + 1e-9:
        axis = np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def _surface_frame(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted centroid and principal axes of the surface; works on open meshes."""
    centers, weights = mesh.triangles_center, mesh.area_faces
    centroid = (centers * weights[:, None]).sum(0) / weights.sum()
    d = centers - centroid
    covariance = (d.T * weights) @ d / weights.sum()
    _, vectors = np.linalg.eigh(covariance)
    return centroid, vectors.T


def _loop_area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _inside(points: np.ndarray, loop: np.ndarray) -> np.ndarray:
    """Even-odd test of each point against one closed loop."""
    xs, ys = loop[:, 0], loop[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    result = np.empty(len(points), dtype=bool)
    step = max(1, PAIRS // len(loop))  # bounds the points x edges arrays
    for first in range(0, len(points), step):
        x, y = points[first : first + step, :1], points[first : first + step, 1:]
        crosses = ((ys > y) != (yn > y)) & (x < (xn - xs) * (y - ys) / (yn - ys + 1e-30) + xs)
        result[first : first + step] = np.count_nonzero(crosses, axis=1) % 2 == 1
    return result


def _boxes(loops: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    return np.array([loop.min(axis=0) for loop in loops]), np.array([loop.max(axis=0) for loop in loops])


def _material_area(loops: list[np.ndarray]) -> float:
    """Area of a closed section: a loop inside an odd number of others cuts a hole."""
    starts = np.array([loop[0] for loop in loops])
    lows, highs = _boxes(loops)
    depth = np.zeros(len(loops), dtype=int)
    step = max(1, PAIRS // len(loops))
    for first in range(0, len(loops), step):
        chunk = starts[first : first + step, None]
        # A start can be inside only the loops whose bounding box holds it.
        near = ((chunk >= lows) & (chunk <= highs)).all(axis=2)
        rows = np.arange(len(near))
        near[rows, rows + first] = False
        for index in np.nonzero(near.any(axis=0))[0]:
            held = first + np.nonzero(near[:, index])[0]
            depth[held] += _inside(starts[held], loops[index])
    return sum(abs(_loop_area(loop)) * (1 if d % 2 == 0 else -1) for loop, d in zip(loops, depth))


def _sectors(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Smallest radius per angular sector around the origin and the farthest point of each."""
    radius = np.hypot(x, y)
    sector = ((np.arctan2(y, x) + np.pi) / (2 * np.pi) * SECTORS).astype(int) % SECTORS
    inner, outer_xy = np.full(SECTORS, np.nan), np.full((SECTORS, 2), np.nan)
    for s in range(SECTORS):
        mask = sector == s
        if mask.any():
            k = np.argmax(np.where(mask, radius, -1))
            inner[s] = radius[mask].min()
            outer_xy[s] = x[k], y[k]
    return inner, outer_xy


def _bore(loops: list[np.ndarray], closed: bool, centre: np.ndarray, outer: float) -> float | None:
    """Inscribed radius of the bore around the axis through ``centre``, None without one."""
    if closed:
        lows, highs = _boxes(loops)
        around = np.nonzero(((centre >= lows) & (centre <= highs)).all(axis=1))[0]
        encircling = [loops[i] for i in around if _inside(centre[None], loops[i])[0]]
        if len(encircling) < 2:
            return None
        # The smallest loop around the axis is the bore; its nearest point is the inscribed radius.
        smallest = min(encircling, key=lambda loop: abs(_loop_area(loop)))
        return float(np.hypot(*(_densify(smallest) - centre).T).min())
    # Open section: a bore is the surface well inside the outer radius in every sector.
    points = np.vstack([_densify(loop) for loop in loops]) - centre
    inner, _ = _sectors(*points.T)
    ring = not np.isnan(inner).any() and (inner < 0.9 * outer).all()
    return float(inner.min()) if ring else None


def _densify(loop: np.ndarray) -> np.ndarray:
    # Ten points per segment, so a coarse facet does not leave sectors empty.
    steps = np.linspace(0, 1, 10, endpoint=False)
    start, step = loop[:-1, None, :], (loop[1:] - loop[:-1])[:, None, :]
    return (start + step * steps[None, :, None]).reshape(-1, loop.shape[1])


def _belts(mesh: trimesh.Trimesh, centroid: np.ndarray, axis: np.ndarray) -> tuple[list, float, np.ndarray, np.ndarray]:
    """Sections across the axis: the farthest point per sector around the centroid, the loops
    in the plane of the belt and their area."""
    axis = axis / np.linalg.norm(axis)
    u = np.cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    t = (mesh.vertices - centroid) @ axis
    low, length = float(t.min()), float(np.ptp(t))
    face_t = t[mesh.faces]
    face_low, face_high = face_t.min(axis=1), face_t.max(axis=1)
    pad = 1e-6 * (1.0 + length)  # wider than trimesh's merge tolerance
    rows: list[dict | None] = []
    for i in range(BELTS):
        height = low + (i + 0.5) * length / BELTS
        # Only faces spanning the plane can cross it, so trimesh cuts the same segments
        # without classifying the whole mesh 144 times.
        near = np.nonzero((face_low <= height + pad) & (face_high >= height - pad))[0]
        path = (
            mesh.section(plane_origin=centroid + axis * height, plane_normal=axis, local_faces=near)
            if len(near)
            else None
        )
        loops = [] if path is None else [np.asarray(loop) for loop in path.discrete]
        if not loops:
            rows.append(None)
            continue
        points = np.vstack([_densify(loop) for loop in loops]) - centroid
        _, outer_xy = _sectors(points @ u, points @ v)
        planar = [np.c_[(loop - centroid) @ u, (loop - centroid) @ v] for loop in loops]
        closed = all(np.allclose(loop[0], loop[-1]) for loop in loops)
        area = _material_area(planar) if closed else None
        rows.append({"outer_xy": outer_xy, "loops": planar, "area": area, "closed": closed})
    return rows, length, u, v


def revolution(mesh: trimesh.Trimesh) -> dict:
    """Best axis among principal and coordinate axes by the share of round belts."""
    method = (
        f"surface_sections; {BELTS}_belts_x_{SECTORS}_sectors; principal_and_coordinate_axes; "
        f"round_if_radius_cv_below_{ROUND_CV}"
    )
    if not mesh.area > 0:
        return {"is_revolution": False, "method": method}
    centroid, principal = _surface_frame(mesh)
    axes = list(principal)
    for coordinate in np.eye(3):
        if all(abs(float(np.dot(coordinate, a))) < 0.999 for a in axes):
            axes.append(coordinate)
    best = None
    for axis in axes:
        rows, length, u, v = _belts(mesh, centroid, axis)
        fits = []
        for row in rows:
            xy = None if row is None else row["outer_xy"][~np.isnan(row["outer_xy"][:, 0])]
            if xy is None or len(xy) < SECTORS * 0.8:
                fits.append(None)
                continue
            a = np.c_[xy, np.ones(len(xy))]
            sol, *_ = np.linalg.lstsq(a, (xy**2).sum(1), rcond=None)
            centre = sol[:2] / 2
            r = np.hypot(*(xy - centre).T)
            fits.append((centre, float(r.std() / r.mean())))
        # The axis passes through the median centre of the round belts, not the centroid.
        round_centres = [f[0] for f in fits if f is not None and f[1] < ROUND_CV]
        shift = np.median(round_centres, axis=0) if round_centres else np.zeros(2)
        cvs, outer_radii, bores, fills = [], [], [], []
        for row, fit in zip(rows, fits):
            if row is None:
                continue
            if fit is None:
                cvs.append(1.0)
                continue
            xy = row["outer_xy"][~np.isnan(row["outer_xy"][:, 0])] - shift
            outer = np.hypot(*xy.T)
            cvs.append(float(outer.std() / outer.mean()))
            outer_radii.append(float(outer.mean()))
            # Measured around the axis: the centroid of a lopsided part is off it.
            bores.append(_bore(row["loops"], row["closed"], shift, float(outer.mean())))
            if row["area"] is not None:
                annulus = math.pi * (outer.mean() ** 2 - (bores[-1] or 0.0) ** 2)
                fills.append(row["area"] / annulus if annulus > 0 else None)
        if not cvs:
            continue
        symmetry = max(0.0, 1 - float(np.median(cvs)))
        round_fraction = sum(cv < ROUND_CV for cv in cvs) / BELTS
        candidate = (round_fraction, symmetry)
        if best is not None and candidate <= best[0]:
            continue
        present = [b for b in bores if b is not None]
        outer_radius = max(outer_radii) if outer_radii else None
        bore_radius = min(present) if present else None
        fill = [f for f in fills if f is not None]
        result = {
            "is_revolution": round_fraction >= 0.6,
            "axis_direction": _vector(axis, 4),
            "axis_point": _vector(centroid + shift[0] * u + shift[1] * v, 3),
            "symmetry_score": _finite(symmetry, 3),
            "round_fraction": _finite(round_fraction, 3),
            "outer_diameter_mm": _finite(2 * outer_radius, 2) if outer_radius else None,
            "length_along_axis_mm": _finite(length, 2),
            "bore": _present({
                "through": len(bores) == BELTS and all(b is not None for b in bores),
                "diameter_mm": _finite(2 * bore_radius, 2),
                "length_mm": _finite(len(present) * length / BELTS, 2),
            }) if bore_radius is not None else None,
            # Outer radius is a mean over sectors, so a non-round section can overfill the ring.
            "annulus_fill": _finite(min(1.0, float(np.median(fill))), 3) if fill else None,
            # Without a bore the wall reaches the axis: (R - 0) / R.
            "wall_to_radius": _finite(max(0.0, 1 - (bore_radius or 0.0) / outer_radius), 3)
            if outer_radius
            else None,
            "belts": BELTS,
            "sectors": SECTORS,
            "method": method,
        }
        best = (candidate, _present(result, keep=("bore",)))
    return best[1] if best else {"is_revolution": False, "method": method}


def orientations(mesh: trimesh.Trimesh, axis: list[float] | None) -> list[dict]:
    """Up to 12 bed orientations; o1 is always the file as loaded."""
    candidates = [("as_loaded", np.eye(3))]
    for side in ([1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]):
        candidates.append(("axis_aligned", _rotation_between(np.array(side, float), DOWN)))
    normals = np.round(mesh.face_normals, 2)
    groups, inverse = np.unique(normals, axis=0, return_inverse=True)
    totals = np.bincount(inverse.ravel(), weights=mesh.area_faces)
    flat = groups[np.argmax(totals)].astype(float)
    if np.linalg.norm(flat) > 0.5:  # degenerate faces have zero normals
        candidates.append(("largest_flat_face", _rotation_between(flat, DOWN)))
    if axis is not None:
        a = np.array(axis, float)
        candidates.append(("revolution_axis", _rotation_between(a, UP)))
        candidates.append(("revolution_axis", _rotation_between(-a, UP)))
    result, seen = [], []
    for source, rotation in candidates:
        # Rotations that put the same STL direction down are one candidate.
        key = np.round(rotation.T @ DOWN, 3)
        if any(np.allclose(key, k) for k in seen):
            continue
        seen.append(key)
        stats = overhang_stats(mesh, rotation)
        result.append(_present({
            "id": f"o{len(result) + 1}",
            "source": source,
            "rotation": [_vector(row, 6) for row in rotation],
            "overhang_area_mm2": stats["area_mm2"],
            "overhang_area_fraction": stats["area_fraction"],
            "bed_contact_area_mm2": stats["bed_contact_area_mm2"],
            "height_mm": stats["height_mm"],
            "extents_mm": stats["extents_mm"],
        }))
    return result[:12]


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
            "schema_version": "1.2", "status": "partial",
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
    # Stage 2 sections; each is optional, a failure leaves the rest of the report intact.
    extra: dict[str, Any] = {}
    # Overhangs are cheap and go into the checkpoint, so a model cut by the time limit keeps them.
    try:
        extra["overhangs"] = overhangs(mesh)
    except Exception as exc:
        partial_errors["overhangs"] = type(exc).__name__
    base_checkpoint = {
        "schema_version": "1.2", "status": "partial",
        "file": {"path": str(path), **file_info},
        "geometry": geometry, "validation": {"defects": defects},
        "units": {"input_unit": units, "coordinate_unit": "unknown" if units == "unknown" else "mm"},
        "topology": {"component_count": len(parts)},
        **extra,
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
    try:
        extra["revolution"] = revolution(mesh)
    except Exception as exc:
        partial_errors["revolution"] = type(exc).__name__
        extra["revolution"] = None  # contract: null means the analysis did not run
    try:
        axis_of = extra["revolution"] or {}
        extra["orientations"] = orientations(
            mesh, axis_of.get("axis_direction") if axis_of.get("is_revolution") else None
        )
    except Exception as exc:
        partial_errors["orientations"] = type(exc).__name__
    report = {
        "schema_version": "1.2",
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
        **extra,
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
    ]
    o, r = report.get("overhangs"), report.get("revolution")
    if o:
        text.append(
            f"Нависания круче {o['critical_angle_deg']}° в положении из файла: {o.get('area_mm2')} ({o.get('area_fraction')} площади); опора на стол: {o.get('bed_contact_area_mm2')}"
        )
    if r:
        bore = r.get("bore")
        text.append(
            f"Тело вращения: {r['is_revolution']}; доля круглых поясов: {r.get('round_fraction')}; ось: {r.get('axis_direction')}; отверстие: "
            + (f"{bore.get('diameter_mm')}, сквозное: {bore['through']}" if bore else "нет")
        )
    text += [
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
            "Полные измерения, статистика, оболочки, PCA, девять сечений и кандидаты ориентации доступны в соседнем JSON.",
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
                "schema_version": "1.2",
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
                "schema_version": "1.2",
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
