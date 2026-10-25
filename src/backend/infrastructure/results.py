from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from ..domain.results import RESULTS, folder_name, shown_path
from ..ports.operations import ResultFolder


class LocalResultFolders:
    def __init__(self, folder: Path, host_folder: str):
        self.folder, self.host_folder = folder, host_folder

    async def reserve(self, part: str) -> ResultFolder:
        return await asyncio.to_thread(self._reserve, folder_name(part))

    async def write(self, folder: ResultFolder, name: str, data: bytes) -> None:
        await asyncio.to_thread((folder.path / name).write_bytes, data)

    async def discard(self, folder: ResultFolder) -> None:
        """Убирает пустую неиспользованную папку проекта."""
        with contextlib.suppress(OSError):
            await asyncio.to_thread(folder.path.rmdir)

    def _reserve(self, name: str) -> ResultFolder:
        root = self.folder / RESULTS
        root.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            candidate = name if number == 1 else f"{name} ({number})"
            try:
                # имя и папка
                (root / candidate).mkdir()
            except FileExistsError:
                number += 1
                continue
            shown = shown_path(self.folder, self.host_folder, RESULTS, candidate)
            return ResultFolder(root / candidate, shown)
