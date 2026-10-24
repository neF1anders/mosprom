"""One tool of the AI Assistant plugin, called by hand through the pipeline's MCP adapter.

uv run python tools/slicing/mcp_call.py get_state ['{"арг": 1}'] [--folder папка]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.config import Settings  # noqa: E402
from src.backend.infrastructure.files import LocalFiles  # noqa: E402
from src.backend.infrastructure.slicer import (  # noqa: E402
    CallFailed,
    McpSlicer,
    SlicerSettings,
    SlicerUnavailable,
)


def main(argv: list[str]) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}", help="аргументы JSON")
    parser.add_argument("--folder", type=Path, default=settings.slicer_folder)
    args = parser.parse_args(argv)
    run_seconds = settings.slicing_timeout_seconds
    slicer = McpSlicer(
        LocalFiles(settings.data_dir), SlicerSettings(args.folder, "", "127.0.0.1", run_seconds)
    )
    try:
        result = asyncio.run(slicer.call(args.tool, json.loads(args.arguments)))
    except (CallFailed, SlicerUnavailable, httpx.TransportError) as error:
        print("ОШИБКА:", error)
        return 1
    print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
