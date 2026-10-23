"""Stage-1 STL analysis report (stl_analysis.report) -> geometry/0."""

from typing import Optional  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.geometry.features import SCHEMA

_ROUND = 3


def geometry_from_report(stl_analysis):
    # type: (Optional[dict]) -> tuple
    """Return (geometry/0, assumptions, warnings).

    The report has no overhang measurement, so `overhang_area_fraction` stays absent and the rules that
    depend on it do not fire; the caller is told so through an assumption.
    """
    if not stl_analysis or not stl_analysis.get("report"):
        raise TuningError("card has no stl_analysis report: parameter selection needs the model geometry")
    report = stl_analysis["report"]
    file_hash = report.get("file", {}).get("sha256")
    if stl_analysis.get("sha256") and file_hash and file_hash != stl_analysis["sha256"]:
        raise TuningError("stl_analysis.report belongs to another STL (sha256 mismatch)")
    assumptions = [_unit_assumption(report.get("units", {}))]
    assumptions.append(
        "overhang area is not in the stage-1 report: supports are not enabled by geometry, "
        "orientation is taken as loaded"
    )
    measures = report.get("geometry", {})
    low, high = measures.get("bounds") or [None, None]
    if low is None or high is None:
        raise TuningError("stl_analysis.report has no geometry.bounds")
    geometry = {
        "schema": SCHEMA,
        "source": "stage1:stl_analysis",
        "bbox_mm": {
            "min": _rounded(low),
            "max": _rounded(high),
            "size": _rounded([top - bottom for top, bottom in zip(high, low)]),
        },
        "triangle_count": report.get("file", {}).get("triangles"),
    }
    geometry.update(_measured(measures))
    geometry.update(_topology(report))
    geometry.update(_wall(report.get("normal_chords") or {}))
    warnings = ["stl report: %s" % text for text in report.get("warnings", [])]
    warnings.extend("stl report partial error: %s" % (error,) for error in report.get("partial_errors") or [])
    return geometry, assumptions, warnings


def _unit_assumption(units):
    unit = units.get("coordinate_unit", "unknown")
    if unit == "mm":
        return "model coordinates are millimetres (confirmed by stage 1)"
    if unit == "unknown":
        return "STL units are unknown: coordinates are taken as millimetres"
    raise TuningError("unsupported coordinate unit %r in stl_analysis.report" % unit)


def _rounded(values):
    return [round(float(value), _ROUND) for value in values]


def _measured(measures):
    found = {}
    if measures.get("volume") is not None:
        found["volume_mm3"] = round(float(measures["volume"]), _ROUND)
    if measures.get("surface_area") is not None:
        found["surface_area_mm2"] = round(float(measures["surface_area"]), _ROUND)
    return found


def _topology(report):
    topology = report.get("topology", {})
    is_closed = bool(topology.get("watertight"))
    normals_consistent = bool(topology.get("winding_consistent"))
    negative = any((c.get("signed_volume") or 0.0) < 0 for c in topology.get("components", []))
    defects = report.get("validation", {}).get("defects") or []
    return {
        "is_closed": is_closed,
        "normals_consistent": normals_consistent,
        "volume_sign_negative": negative,
        "needs_repair": not (is_closed and normals_consistent) or negative or bool(defects),
    }


def _wall(chords):
    if chords.get("minimum_sampled") is None:
        return {}
    # Shortest sampled inward chord: an estimate that can miss thin features (see report limitations).
    return {"min_wall_estimate_mm": round(float(chords["minimum_sampled"]), _ROUND), "min_wall_is_estimate": True}
