"""Independent binary STL cross-check, without importing Trimesh.

Usage: python tests/verify_stl_reports.py /path/to/report-directory
Only binary STL is supported here; ASCII and defects have separate pytest cases.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def verify(report: dict) -> dict:
    path = Path(report["file"]["path"])
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + 50 * count, "Verification requires exact binary STL"
    records = np.frombuffer(
        data,
        dtype=np.dtype(
            [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
        ),
        offset=84,
        count=count,
    )
    triangles = (
        records["vertices"].astype(np.float64) * report["units"]["scale_applied"]
    )
    vertices, face_indices = np.unique(
        triangles.reshape(-1, 3), axis=0, return_inverse=True
    )
    faces = face_indices.reshape(-1, 3)
    edges = np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    graph = coo_matrix(
        (np.ones(len(unique_edges)), (unique_edges[:, 0], unique_edges[:, 1])),
        shape=(len(vertices), len(vertices)),
    )
    component_count, _ = connected_components(graph, directed=False)
    area = (
        np.linalg.norm(
            np.cross(
                triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
            ),
            axis=1,
        ).sum()
        / 2
    )
    relative = triangles - vertices.mean(axis=0)
    signed_volume = (
        np.einsum(
            "ij,ij->i", relative[:, 0], np.cross(relative[:, 1], relative[:, 2])
        ).sum()
        / 6
    )
    g, t = report["geometry"], report["topology"]
    assert hashlib.sha256(data).hexdigest() == report["file"]["sha256"]
    assert count == report["file"]["triangles"]
    np.testing.assert_allclose(np.ptp(vertices, axis=0), g["extents"], rtol=1e-10)
    np.testing.assert_allclose(area, g["surface_area"], rtol=1e-10)
    assert int((counts == 1).sum()) == t["boundary_edges"]
    assert int((counts > 2).sum()) == t["nonmanifold_edges"]
    assert component_count == t["component_count"]
    if g["volume"] is not None:
        np.testing.assert_allclose(signed_volume, g["volume"], rtol=1e-9)
    else:
        np.testing.assert_allclose(
            signed_volume, sum(p["signed_volume"] for p in t["components"]), rtol=1e-9
        )
    return {
        "file": str(path),
        "verified": True,
        "triangles": count,
        "extents": g["extents"],
        "surface_area": float(area),
        "signed_volume_integral": float(signed_volume),
        "components": int(component_count),
        "sha256_unchanged": True,
    }


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    results = [
        verify(json.loads((directory / item["json"]).read_text(encoding="utf-8")))
        for item in index
    ]
    (directory / "verification.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Independent binary STL verification passed: {len(results)}/{len(index)}")
