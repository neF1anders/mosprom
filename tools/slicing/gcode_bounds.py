#!/usr/bin/env python3
"""Габариты печати по движениям G-code: python gcode_bounds.py <result.gcode> [--above-z 6]
Печатает X/Y/Z (мин, макс, центр, размер) в машинных координатах; центр стола classic: X 175.5, Y 150.15.
С --above-z считает только движения с экструзией выше этой высоты (например, стойку над основанием)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_gcode import parse_gcode

WORD = re.compile(r"([XYZE])(-?\d+(?:\.\d+)?)")


def above_z_bounds(path, threshold):
    z, e_prev = 0.0, None
    lo, hi = {"x": None, "y": None}, {"x": None, "y": None}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line[:2] not in ("G0", "G1") or ";" in line[:1]:
                continue
            w = {k: float(v) for k, v in WORD.findall(line.split(";")[0])}
            if "Z" in w:
                z = w["Z"]
            extruding = "E" in w and (e_prev is None or w["E"] > e_prev)
            if "E" in w:
                e_prev = w["E"]
            if extruding and z > threshold and "X" in w and "Y" in w:
                for axis in "xy":
                    v = w[axis.upper()]
                    lo[axis] = v if lo[axis] is None else min(lo[axis], v)
                    hi[axis] = v if hi[axis] is None else max(hi[axis], v)
    return {a: [lo[a], hi[a]] for a in "xy"}


def show(b):
    for axis, (lo, hi) in b.items():
        if lo is None:
            print(axis.upper(), "нет движений")
        else:
            print("%s: мин %.2f, макс %.2f, центр %.2f, размер %.2f" % (axis.upper(), lo, hi, (lo + hi) / 2, hi - lo))


def main(argv):
    args = argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        return 2
    if "--above-z" in args:
        show(above_z_bounds(args[0], float(args[args.index("--above-z") + 1])))
    else:
        show(parse_gcode(args[0])["bounds"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
