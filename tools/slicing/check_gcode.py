"""Checks a G-code of STE Slicer against the parameter set it was sliced from, as the pipeline's
stage five does (``src/backend/slicing/gcode.py``).

    uv run python tools/slicing/check_gcode.py result.gcode набор.json [--iteration N] [--json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.config import Settings  # noqa: E402
from src.backend.domain.parameters import ParameterSet  # noqa: E402
from src.backend.infrastructure.catalog import load_catalog  # noqa: E402
from src.backend.slicing import check_gcode, read_gcode  # noqa: E402

_RESULTS = {"ok": "ОК", "needs_changes": "НУЖНЫ ИЗМЕНЕНИЯ", "apply_failed": "ОШИБКА ПРИМЕНЕНИЯ"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("gcode", type=Path, help="файл G-code")
    parser.add_argument("parameter_set", type=Path, help="файл stage2.parameter_set JSON")
    parser.add_argument("--iteration", type=int, default=1, help="номер захода")
    parser.add_argument("--json", action="store_true", help="итог в JSON")
    args = parser.parse_args(argv)
    settings = Settings()
    parameter_set = ParameterSet.model_validate_json(args.parameter_set.read_text("utf-8"))
    with args.gcode.open(encoding="utf-8", errors="replace") as stream:
        facts = read_gcode(stream)
    catalog = load_catalog(settings.build_dir, settings.printer)
    result = check_gcode(facts, parameter_set, catalog, args.iteration)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Итог: {_RESULTS[result.result]}")
        for finding in result.findings:
            print(f"  [{finding.level}] {finding.kind}: {finding.message}")
    return 0 if result.result == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
