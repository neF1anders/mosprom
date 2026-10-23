"""Deterministic geometry features of an STL mesh (contract geometry/0)."""
import math

from tuning.geometry.stl import read_triangles

SCHEMA = "geometry/0"
OVERHANG_ANGLE_DEG = 45.0
_VERTEX_PRECISION = 4
_BED_CONTACT_TOLERANCE_MM = 0.01


def extract_features(path):
    # type: (str) -> dict
    coordinates = read_triangles(path)
    triangle_count = len(coordinates) // 9
    low, high = _bounding_box(coordinates)
    volume, area, overhang_area = _measure(coordinates, low[2])
    is_closed, normals_consistent = _topology(coordinates)
    volume_mm3 = abs(volume)
    return {
        "schema": SCHEMA,
        "triangle_count": triangle_count,
        "bbox_mm": {
            "min": _rounded(low),
            "max": _rounded(high),
            "size": _rounded([h - l for h, l in zip(high, low)]),
        },
        "volume_mm3": round(volume_mm3, 3),
        "surface_area_mm2": round(area, 3),
        "is_closed": is_closed,
        "normals_consistent": normals_consistent,
        "volume_sign_negative": volume < 0,
        "needs_repair": not (is_closed and normals_consistent) or volume < 0,
        "overhang_angle_deg": OVERHANG_ANGLE_DEG,
        "overhang_area_fraction": round(overhang_area / area, 4) if area else 0.0,
        # Estimate only: exact for a thin plate (2V/A), an overestimate for chunky parts.
        "min_wall_estimate_mm": round(2.0 * volume_mm3 / area, 3) if area else 0.0,
        "min_wall_is_estimate": True,
    }


def _rounded(values):
    return [round(value, 3) for value in values]


def _bounding_box(coordinates):
    low = [min(coordinates[axis::3]) for axis in range(3)]
    high = [max(coordinates[axis::3]) for axis in range(3)]
    return low, high


def _measure(coordinates, bed_z):
    """One pass: signed volume, surface area, area of overhanging faces."""
    volume = 0.0
    area = 0.0
    overhang_area = 0.0
    # Downward faces steeper than the threshold from vertical: normal z < -sin(angle).
    limit = -math.sin(math.radians(OVERHANG_ANGLE_DEG))
    for offset in range(0, len(coordinates), 9):
        ax, ay, az, bx, by, bz, cx, cy, cz = coordinates[offset:offset + 9]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        doubled_area = math.sqrt(nx * nx + ny * ny + nz * nz)
        if doubled_area == 0.0:
            continue
        triangle_area = doubled_area / 2.0
        area += triangle_area
        volume += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6.0
        on_bed = max(az, bz, cz) - bed_z <= _BED_CONTACT_TOLERANCE_MM
        if nz / doubled_area < limit and not on_bed:
            overhang_area += triangle_area
    return volume, area, overhang_area


def _topology(coordinates):
    """Closed = every edge shared by two faces; consistent = those faces traverse it in opposite directions."""
    vertex_ids = {}
    corners = []
    for offset in range(0, len(coordinates), 3):
        key = (
            round(coordinates[offset], _VERTEX_PRECISION),
            round(coordinates[offset + 1], _VERTEX_PRECISION),
            round(coordinates[offset + 2], _VERTEX_PRECISION),
        )
        corners.append(vertex_ids.setdefault(key, len(vertex_ids)))
    base = len(vertex_ids)
    edges = []
    for offset in range(0, len(corners), 3):
        ring = corners[offset:offset + 3]
        for start, end in zip(ring, ring[1:] + ring[:1]):
            if start == end:
                continue
            # Low bit encodes direction; the rest identifies the undirected edge.
            edges.append((min(start, end) * base + max(start, end)) * 2 + (1 if start < end else 0))
    edges.sort()
    if len(edges) % 2:
        return False, False
    is_closed = True
    normals_consistent = True
    for index in range(0, len(edges), 2):
        first, second = edges[index], edges[index + 1]
        if first >> 1 != second >> 1:
            return False, False
        if index + 2 < len(edges) and second >> 1 == edges[index + 2] >> 1:
            is_closed = False
        if first & 1 == second & 1:
            normals_consistent = False
    return is_closed, normals_consistent
