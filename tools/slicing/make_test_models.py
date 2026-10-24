#!/usr/bin/env python3
"""Делает две несимметричные тестовые детали (бинарный STL, мм, Z вверх):
  l_bracket.stl: основание 40x20x5 и стойка 5x10x20 сверху у края (40x20x25 в сумме); нужна для знака поворота;
  mushroom.stl: ножка 10x10x20 и плита 40x40x4 сверху (нависание 15 мм со всех сторон); нужна для поддержек.
Использование: python make_test_models.py <папка_вывода>"""
import os, struct, sys


def box(x0, y0, z0, x1, y1, z1):
    v = {(a, b, c): (x, y, z) for a, x in enumerate((x0, x1)) for b, y in enumerate((y0, y1)) for c, z in enumerate((z0, z1))}
    quads = [  # (нормаль, четыре угла против часовой стрелки снаружи)
        ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
        ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
        ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
        ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
        ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
        ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ]
    tris = []
    for n, q in quads:
        p = [v[k] for k in q]
        tris.append((n, p[0], p[1], p[2]))
        tris.append((n, p[0], p[2], p[3]))
    return tris


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"mosprom test model".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    os.makedirs(argv[1], exist_ok=True)
    write_stl(os.path.join(argv[1], "l_bracket.stl"), box(0, 0, 0, 40, 20, 5) + box(0, 0, 5, 5, 10, 25))
    write_stl(os.path.join(argv[1], "mushroom.stl"), box(15, 15, 0, 25, 25, 20) + box(0, 0, 20, 40, 40, 24))
    print("l_bracket.stl, mushroom.stl")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
