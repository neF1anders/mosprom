from __future__ import annotations

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

RESULTS = "Результаты"
# запрещённые символы Windows
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}
NAME_CHARS = 60
UNNAMED = "Деталь"


def folder_name(part: str) -> str:
    """Имя части как папки."""
    name = " ".join(FORBIDDEN.sub(" ", part).split())[:NAME_CHARS].strip(" .")
    if not name or name.split(".")[0].upper() in DEVICES:
        return UNNAMED
    return name


def shown_path(folder: Path, host_folder: str, *parts: str) -> str:
    """Путь так, как видит слайсер."""
    if not host_folder:
        return str(folder.joinpath(*parts))
    windows = re.match(r"^[A-Za-z]:|^\\\\", host_folder)
    base: PurePath = (PureWindowsPath if windows else PurePosixPath)(host_folder)
    return str(base.joinpath(*parts))
