from __future__ import annotations

import re
from typing import Any

import json_repair

from .context import Inputs

# начало каждого документа
DOCUMENT_CHARS = 6000
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def split_tool(
    text: str, name: str, parameters: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Описание инструмента из промпта."""
    block = re.compile(rf"\s*<tool_{name}>\s*(.*?)\s*</tool_{name}>\s*", re.S)
    match = block.search(text)
    tool = {
        "type": "function",
        "function": {
            "name": name,
            "description": match.group(1) if match else "",
            "parameters": parameters or {"type": "object", "properties": {}},
        },
    }
    return block.sub("\n", text).strip() + "\n", tool


def documents(inputs: Inputs) -> str:
    """Начало каждого документа для описания."""
    files: dict[str, list[str]] = {}
    for page in inputs.documents:
        files.setdefault(page.filename, []).append(page.text)
    return "\n\n".join(
        f"{name}\n{chr(10).join(pages).strip()[:DOCUMENT_CHARS]}" for name, pages in files.items()
    ).strip()


def called(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Аргументы первого вызова инструмента."""
    for call in tool_calls:
        function = call.get("function", {})
        if function.get("name") == name:
            arguments = json_repair.loads(function.get("arguments") or "{}")
            return arguments if isinstance(arguments, dict) else {}
    return None


def chat_text(text: str) -> str:
    """Markdown в виде для чата."""
    text = _CJK.sub("", text)
    text = re.sub(r"\s*:[ \t]*$", "", text, flags=re.M)
    # двоеточие перед пробелом
    text = re.sub(r"(?<=\S):(?=\s)", ",", text)
    # тире реплики
    text = re.sub(r"(?m)^([ \t]*)[—–][ \t]*", r"\1", text)
    text = re.sub(r",?\s+[—–]\s+", ", ", text)
    # диапазон остаётся дефисом
    text = re.sub(r"(?<=\w)[—–](?=\w)", "-", text)
    return text.strip().removesuffix(".")
