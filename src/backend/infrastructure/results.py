"""Every finished project keeps its files in a folder of its own, named after the part.

The folders sit in ``Результаты`` inside the folder shared with the slicer, so the user finds
them beside the slicer's own files. A name an earlier project took gets a number: a new
project never overwrites an old one.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from ..ports.operations import ResultFolder

RESULTS = "Результаты"
# Characters Windows refuses in a file name, and the names it keeps for devices.
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}
NAME_CHARS = 60
UNNAMED = "Деталь"


def folder_name(part: str) -> str:
    """The part's name as a folder name on any system; Windows drops trailing dots."""
    name = " ".join(FORBIDDEN.sub(" ", part).split())[:NAME_CHARS].strip(" .")
    if not name or name.split(".")[0].upper() in DEVICES:
        return UNNAMED
    return name


def shown_path(folder: Path, host_folder: str, *parts: str) -> str:
    """A path inside the shared folder as the slicer's machine sees it."""
    if not host_folder:
        return str(folder.joinpath(*parts))
    windows = re.match(r"^[A-Za-z]:|^\\\\", host_folder)
    base: PurePath = (PureWindowsPath if windows else PurePosixPath)(host_folder)
    return str(base.joinpath(*parts))


class LocalResultFolders:
    def __init__(self, folder: Path, host_folder: str):
        self.folder, self.host_folder = folder, host_folder

    async def reserve(self, part: str) -> ResultFolder:
        return await asyncio.to_thread(self._reserve, folder_name(part))

    async def write(self, folder: ResultFolder, name: str, data: bytes) -> None:
        await asyncio.to_thread((folder.path / name).write_bytes, data)

    async def discard(self, folder: ResultFolder) -> None:
        """A folder left unused goes; one with files in it stays."""
        with contextlib.suppress(OSError):
            await asyncio.to_thread(folder.path.rmdir)

    def _reserve(self, name: str) -> ResultFolder:
        root = self.folder / RESULTS
        root.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            candidate = name if number == 1 else f"{name} ({number})"
            try:
                # Taking the name and making the folder is one step, so two projects
                # finishing at once never share a folder.
                (root / candidate).mkdir()
            except FileExistsError:
                number += 1
                continue
            shown = shown_path(self.folder, self.host_folder, RESULTS, candidate)
            return ResultFolder(root / candidate, shown)
