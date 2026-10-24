#!/usr/bin/env python3
"""Делает набор тестовых parameter_set для проверки apply_parameter_set.py на настоящем слайсере.
Использование: python make_apply_test_sets.py <tests/slicing/example_bracket_petg_classic.json> <папка_вывода>"""
import copy, json, math, os, sys


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def variant(base, name, edit):
    p = copy.deepcopy(base)
    edit(p)
    return name, p


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    base = json.load(open(argv[1], encoding="utf-8"))
    out = argv[2]
    os.makedirs(out, exist_ok=True)

    def tr(p):
        return p["models"][0]["transform"]

    variants = [
        variant(base, "v00_base", lambda p: None),
        variant(base, "v01_rot_x90", lambda p: tr(p).update(rotation=rot_x(90))),
        variant(base, "v02_rot_x_minus90", lambda p: tr(p).update(rotation=rot_x(-90))),
        variant(base, "v03_rot_z90", lambda p: tr(p).update(rotation=rot_z(90))),
        variant(base, "v04_rot_y45", lambda p: tr(p).update(rotation=rot_y(45))),
        variant(base, "v05_move_30_20", lambda p: tr(p).update(position=[30.0, 20.0, 0.0])),
        variant(base, "v06_scale_half", lambda p: tr(p).update(scale=[0.5, 0.5, 0.5])),
        variant(base, "v07_clamp_layer", lambda p: p["settings"].update(
            layer_height={"value": 0.001, "why": "тест подрезки", "source": "assumption:A1"})),
        variant(base, "v08_unsupported_scale", lambda p: tr(p).update(scale=[1, 1, 2])),
        variant(base, "v09_clamp_density", lambda p: p["settings"].update(
            infill_sparse_density={"value": 150, "unit": "%", "why": "тест подрезки: максимум 100", "source": "assumption:A1"})),
        variant(base, "v10_support_on", lambda p: p["settings"].update(
            support_enable={"value": True, "why": "тест поддержек", "source": "assumption:A1"})),
        variant(base, "v11_support_off", lambda p: None),
        variant(base, "v12_rot_y90", lambda p: tr(p).update(rotation=rot_y(90))),
        variant(base, "v13_rot_y_minus90", lambda p: tr(p).update(rotation=rot_y(-90))),
    ]
    for name, p in variants:
        with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
