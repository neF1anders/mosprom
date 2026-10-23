from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..domain.errors import AppError, NotFound
from ..domain.limits import InputLimits


class LocalFiles:
    def __init__(self, root: Path, timeout: float | None = None, limits: InputLimits | None = None):
        self.root = root.resolve()
        self.limits = limits or InputLimits()
        self.timeout = timeout or self.limits.analysis_seconds
        self._slots = asyncio.Semaphore(2)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:\.(?:png|json))?", key):
            raise NotFound()
        return self.root / key

    async def put(self, key: str, chunks: AsyncIterator[bytes], limit: int) -> tuple[str, int]:
        target = self.path(key)
        temporary = self.path(str(uuid4()))
        size, digest = 0, hashlib.sha256()
        stream = await asyncio.to_thread(temporary.open, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise AppError("Файл превышает допустимый размер", "file_too_large", 413)
                digest.update(chunk)
                await asyncio.to_thread(stream.write, chunk)
            if not size:
                raise AppError("Файл пуст", "empty_file")
        except BaseException:
            await asyncio.to_thread(stream.close)
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise
        await asyncio.to_thread(stream.close)
        await asyncio.to_thread(temporary.replace, target)
        return digest.hexdigest(), size

    async def read(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self.path(key).read_bytes)
        except FileNotFoundError as exc:
            raise NotFound() from exc

    async def remove(self, key: str) -> None:
        await asyncio.to_thread(self.path(key).unlink, missing_ok=True)

    async def inspect(self, key: str, kind: str) -> dict[str, Any]:
        return await self._run(
            "document",
            key,
            kind,
            str(uuid4()) + ".json",
            self.limits.pdf_pages * self.limits.page_seconds if kind == "pdf" else self.timeout,
        )

    async def analyze(self, key: str, units: str, cache_key: str) -> dict[str, Any]:
        return await self._run("mesh", key, units, cache_key + ".json", self.timeout)

    async def _run(
        self, mode: str, key: str, argument: str, output_key: str, timeout: float
    ) -> dict[str, Any]:
        async with self._slots:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "src.backend.infrastructure.process_runner",
                mode,
                str(self.path(key)),
                argument,
                str(self.path(output_key)),
                self.limits.model_dump_json(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout)
            except (TimeoutError, asyncio.CancelledError) as exc:
                process.kill()
                await process.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return await self._partial(output_key, "timeout")
            if process.returncode:
                return await self._partial(output_key, "process_crash")
            result = json.loads(await self.read(output_key))
            if "error" in result and "geometry" not in result:
                raise AppError(
                    result["error"], result.get("code", "process_error"), result.get("status", 422)
                )
            return result

    async def _partial(self, key: str, error: str) -> dict[str, Any]:
        try:
            result = json.loads(await self.read(key))
        except NotFound:
            raise AppError(
                "Анализ не завершён, ранее проверенные данные сохранены", error, 503
            ) from None
        result.setdefault("partial_errors", {})["process"] = error
        result["status"] = "partial"
        return result
