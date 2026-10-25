from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from ..domain.errors import NotFound
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

    async def read(self, folder: str, name: str) -> bytes:
        """Читает файл из папки проекта."""
        if not _plain(folder) or not _plain(name):
            raise NotFound()
        try:
            return await asyncio.to_thread((self.folder / RESULTS / folder / name).read_bytes)
        except OSError:
            raise NotFound() from None

    async def files(self, folder: str) -> list[dict[str, Any]] | None:
        """Файлы папки прямо сейчас."""
        if not _plain(folder):
            return None
        return await asyncio.to_thread(_listing, self.folder / RESULTS / folder)

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


def _plain(name: str) -> bool:
    return name not in ("", ".", "..") and not set(name) & set("/\\:") and Path(name).name == name


def _listing(path: Path) -> list[dict[str, Any]] | None:
    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return None
    return [{"name": e.name, "size": e.stat().st_size} for e in entries if e.is_file()]
