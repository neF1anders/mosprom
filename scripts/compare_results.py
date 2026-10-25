from __future__ import annotations

import argparse
import configparser
import re
import sys
import zipfile
from pathlib import Path

SETTINGS = (
    ("layer_height", "Слой"),
    ("wall_thickness", "Стенки"),
    ("infill_sparse_density", "Заполнение"),
    ("support_enable", "Поддержки"),
    ("adhesion_type", "Адгезия"),
)
HEADER = re.compile(r"^;(PRINTING_MODE|TIME|Filament used|LAYER_COUNT):\s*(.*?)\s*$")


def project(path: Path) -> dict[str, str]:
    """Что сохранил слайсер в проекте."""
    found: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".cfg"):
                continue
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(archive.read(name).decode("utf-8", "replace"))
            kind = config.get("metadata", "type", fallback="")
            if kind == "quality" and config.get("metadata", "global_quality", fallback=""):
                found["profile"] = config.get("metadata", "quality_type", fallback="")
            elif kind == "user" and config.has_section("values"):
                found.update(config.items("values"))
            elif kind == "extruder_train" and config.get("metadata", "position") == "0":
                found["material"] = config.get("containers", "3", fallback="")
    return found


def gcode(path: Path) -> dict[str, str]:
    """Строки заголовка G-code файла."""
    times: list[float] = []
    filament: list[float] = []
    found: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if not line.startswith(";"):
                continue
            match = HEADER.match(line)
            if not match:
                continue
            key, value = match.groups()
            if key == "TIME":
                times.append(float(value))
            elif key == "Filament used":
                filament.append(float(value.split("m")[0]))
            else:
                found.setdefault(key, value)
    hours, minutes = divmod(round(sum(times) / 60), 60)
    found["time"] = f"{hours} ч {minutes} мин" if times else "нет"
    found["filament"] = f"{sum(filament):.2f} м" if filament else "нет"
    return found


def row(folder: Path) -> list[str]:
    if not (folder / "project.3mf").exists() or not (folder / "result.gcode").exists():
        return [folder.name, "нет файлов"] + [""] * (len(SETTINGS) + 6)
    settings, header = project(folder / "project.3mf"), gcode(folder / "result.gcode")
    return [
        folder.name,
        header.get("PRINTING_MODE", "").strip("[]") or settings.get("printing_mode", "classic"),
        settings.get("profile", ""),
        settings.get("material", ""),
        *(settings.get(key, "станд.") for key, _ in SETTINGS),
        header["time"],
        header["filament"],
        header.get("LAYER_COUNT", ""),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Сравнение проектов слайсера двух прогонов.")
    parser.add_argument("--pair", nargs=2, action="append", metavar=("OURS", "THEIRS"))
    pairs = parser.parse_args().pair or []
    if not pairs:
        parser.error("нужна хотя бы одна пара --pair")
    titles = ["Папка", "Режим", "Профиль", "Материал", *(t for _, t in SETTINGS)]
    titles += ["Время", "Филамент", "Слоёв"]
    print("| " + " | ".join(titles) + " |")
    print("|" + "---|" * len(titles))
    for ours, theirs in pairs:
        for folder in (Path(ours), Path(theirs)):
            print("| " + " | ".join(row(folder)) + " |")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
