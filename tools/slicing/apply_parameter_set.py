"""Applies a parameter set in STE Slicer through the AI Assistant plugin, without the chat.

The pipeline's own plan and MCP adapter do the work (``src/backend/slicing``,
``src/backend/infrastructure/slicer.py``): the models go to ``mosprom/<run>`` in the plugin's
folder, the slicer saves ``result.gcode`` and ``project.3mf`` there, copies come to
``--out-dir`` and the G-code is checked against the set.

    uv run python tools/slicing/apply_parameter_set.py набор.json --model <attachment_id>=путь.stl
        [--folder ~/Documents/STE_AIAssistant] [--out-dir папка] [--check] [--dry-run]
        [--report report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.config import Settings  # noqa: E402
from src.backend.domain.catalog import Catalog  # noqa: E402
from src.backend.domain.parameters import ParameterSet  # noqa: E402
from src.backend.infrastructure.catalog import load_catalog  # noqa: E402
from src.backend.infrastructure.files import LocalFiles  # noqa: E402
from src.backend.infrastructure.slicer import McpSlicer, SlicerSettings, gcode_facts  # noqa: E402
from src.backend.slicing import build_plan, check_gcode  # noqa: E402
from src.backend.validation.checks import check_parameters  # noqa: E402


def main(argv: list[str]) -> int:
    # The build and the plugin's folder as the worker reads them, ``.env`` included; the script
    # runs next to the slicer, so the folder is the slicer's own.
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("parameter_set", type=Path, help="файл stage2.parameter_set JSON")
    parser.add_argument("--model", action="append", default=[], help="attachment_id=путь.stl")
    parser.add_argument("--folder", type=Path, default=settings.slicer_folder)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/slicing"))
    parser.add_argument("--check", action="store_true", help="сначала проверка этапа 3")
    parser.add_argument("--dry-run", action="store_true", help="план вызовов без слайсера")
    parser.add_argument("--report", type=Path, help="куда записать отчёт нарезки JSON")
    args = parser.parse_args(argv)
    parameter_set = ParameterSet.model_validate_json(args.parameter_set.read_text("utf-8"))
    paths = dict(spec.split("=", 1) for spec in args.model)
    if args.dry_run:
        return _plan(parameter_set, paths)
    catalog = load_catalog(settings.build_dir, settings.printer)
    if args.check and not _checked(parameter_set, catalog):
        return 1
    files = LocalFiles(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for attachment_id, path in paths.items():
        shutil.copyfile(path, files.path(attachment_id))
    run_seconds = settings.slicing_timeout_seconds
    slicer = McpSlicer(files, SlicerSettings(args.folder, "", "127.0.0.1", run_seconds))
    run = time.strftime("manual-%Y%m%d-%H%M%S")
    report = asyncio.run(slicer.slice(run, parameter_set, {a: a for a in paths}))
    if args.report:
        args.report.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.model_dump_json(indent=2, include={"status", "message", "steps", "clamped"}))
    if report.gcode is None:
        return 1
    result = check_gcode(gcode_facts(files, report.gcode), parameter_set, catalog, 1)
    for finding in result.findings:
        print(f"[{finding.level}] {finding.kind}: {finding.message}")
    print(f"Проверка G-code: {result.result}; файлы {report.folder}")
    return 0 if result.result == "ok" else 1


def _plan(parameter_set: ParameterSet, paths: dict[str, str]) -> int:
    calls, unsupported = build_plan(parameter_set, paths, "result.gcode", "project.3mf")
    for call in calls:
        print(call.step, json.dumps(call.args, ensure_ascii=False))
    for item in unsupported:
        print("не отправлено", item.step, item.reason)
    return 0


def _checked(parameter_set: ParameterSet, catalog: Catalog) -> bool:
    """Stage three's findings; a set with errors is not applied."""
    issues = check_parameters(parameter_set, catalog)
    for issue in issues:
        print(f"[{issue.level}] {issue.where}: {issue.message}")
    if any(issue.level == "error" for issue in issues):
        print("Набор с ошибками этапа 3 не применён")
        return False
    return True


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
