"""Synthetic STL meshes for tests; outward-facing counter-clockwise triangles."""
import math
import struct


def cube(size):
    s = float(size)
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (3, 7, 6), (3, 6, 2),
        (0, 4, 7), (0, 7, 3),
        (1, 2, 6), (1, 6, 5),
    ]
    return [tuple(v[i] for i in face) for face in faces]


def frustum(bottom_radius, top_radius, height, segments=24):
    """Cylinder-like solid; top radius much wider than bottom gives real overhangs."""
    def ring(radius, z):
        return [
            (radius * math.cos(2 * math.pi * i / segments), radius * math.sin(2 * math.pi * i / segments), z)
            for i in range(segments)
        ]

    bottom, top = ring(bottom_radius, 0.0), ring(top_radius, float(height))
    low_center, high_center = (0.0, 0.0, 0.0), (0.0, 0.0, float(height))
    triangles = []
    for i in range(segments):
        j = (i + 1) % segments
        triangles.append((bottom[i], bottom[j], top[j]))
        triangles.append((bottom[i], top[j], top[i]))
        triangles.append((low_center, bottom[j], bottom[i]))
        triangles.append((high_center, top[i], top[j]))
    return triangles


def _normal(triangle):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def write_binary(path, triangles, header=b"synthetic"):
    with open(str(path), "wb") as stream:
        stream.write(header.ljust(80, b" "))
        stream.write(struct.pack("<I", len(triangles)))
        for triangle in triangles:
            flat = [c for vertex in triangle for c in vertex]
            stream.write(struct.pack("<12fH", *(_normal(triangle) + tuple(flat) + (0,))))


def write_ascii(path, triangles):
    lines = ["solid synthetic"]
    for triangle in triangles:
        lines.append("facet normal %g %g %g" % _normal(triangle))
        lines.append("  outer loop")
        lines.extend("    vertex %r %r %r" % vertex for vertex in triangle)
        lines.extend(["  endloop", "endfacet"])
    lines.append("endsolid synthetic")
    with open(str(path), "w") as stream:
        stream.write("\n".join(lines) + "\n")
