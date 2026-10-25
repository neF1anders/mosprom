from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.slicing import read_gcode  # noqa: E402
from src.backend.slicing.gcode import Bounds  # noqa: E402

_WORD = re.compile(r"([XYZE])(-?\d+(?:\.\d+)?)")


def above_z(path: Path, threshold: float) -> dict[str, Bounds]:
    bounds = {axis: Bounds() for axis in "XY"}
    z, extruded = 0.0, None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line[:2] not in ("G0", "G1"):
                continue
            words = {k: float(v) for k, v in _WORD.findall(line.split(";")[0])}
            z = words.get("Z", z)
            extruding = "E" in words and (extruded is None or words["E"] > extruded)
            extruded = words.get("E", extruded)
            if extruding and z > threshold and "X" in words and "Y" in words:
                for axis in "XY":
                    bounds[axis].add(words[axis])
    return bounds


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Границы печати G-code в координатах станка.")
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--above-z", type=float)
    args = parser.parse_args(argv)
    if args.above_z is not None:
        bounds = above_z(args.gcode, args.above_z)
    else:
        with args.gcode.open(encoding="utf-8", errors="replace") as stream:
            bounds = read_gcode(stream).bounds
    for axis, found in bounds.items():
        if found.low is None or found.high is None:
            print(axis, "нет движений")
            continue
        centre, size = (found.low + found.high) / 2, found.high - found.low
        print(
            f"{axis}: мин {found.low:.2f}, макс {found.high:.2f}, центр {centre:.2f}, размер {size:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
