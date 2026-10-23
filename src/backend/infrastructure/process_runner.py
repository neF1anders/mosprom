"""One disposable process per untrusted document/mesh. JSON checkpoints survive timeout."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ..domain.errors import AppError
from ..domain.limits import InputLimits
from .documents import inspect_document


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def analyze(path: Path, units: str, output: Path, limits: InputLimits | None = None) -> dict:
    from src.mesh_analysis import analyze_stl, write_preview

    limits = limits or InputLimits()

    try:
        result = analyze_stl(
            path,
            units=units,
            max_bytes=limits.stl_mib * 1024 * 1024,
            max_faces=limits.triangles,
            samples=128,
            checkpoint=lambda report: write_json(output, report),
        )
    except ValueError as exc:
        raise AppError("Файл STL повреждён или не читается", "invalid_stl") from exc
    try:
        preview = output.with_suffix(".png")
        write_preview(path, preview)
        result["preview"] = preview.name
    except Exception as exc:
        result.setdefault("partial_errors", {})["preview"] = type(exc).__name__
    return result


def main() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (1500, 1500))
        if sys.platform == "linux":
            resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    except ImportError:
        pass  # Windows container limits are enforced at deployment boundary.
    mode, raw_path, argument, raw_output = sys.argv[1:5]
    limits = InputLimits.model_validate_json(sys.argv[5]) if len(sys.argv) > 5 else InputLimits()
    path, output = Path(raw_path), Path(raw_output)
    try:
        result = (
            inspect_document(path, argument, limits)
            if mode == "document"
            else analyze(path, argument, output, limits)
        )
    except AppError as exc:
        result = {"error": exc.message, "code": exc.code, "status": exc.status}
    except Exception as exc:
        result = {
            "error": "Обработка не завершена",
            "code": "process_error",
            "exception_type": type(exc).__name__,
        }
        if output.exists():
            result = {
                **json.loads(output.read_text()),
                "partial_errors": {"process": type(exc).__name__},
            }
    write_json(output, result)


if __name__ == "__main__":
    main()
