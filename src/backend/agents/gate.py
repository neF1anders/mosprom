"""The first reply to every chat message: talk, ask for details once, or start the work.

The gate starts the work only by calling its tool, so the code reads the decision from the
call and never from the text. Its text reaches the chat as it is, so the rules of the chat
text are enforced here as well, not only asked for in the prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any

import json_repair

from .context import Inputs

START = "start_pipeline"
# Enough of each document to judge what it describes, short enough for a quick reply.
DOCUMENT_CHARS = 6000
NO_TEXT = "Пользователь прислал файлы без текста"
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def split_tool(
    text: str, name: str = START, parameters: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """The tool's own block of the prompt becomes the tool's description."""
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


def gate_messages(
    system: str, messages: list[dict[str, Any]], inputs: Inputs, stl: str | None
) -> list[dict[str, Any]]:
    """The chat as a dialog; the last user turn carries what is attached."""
    turns: list[dict[str, Any]] = []
    for message in messages:
        if turns and turns[-1]["role"] == message["role"]:
            turns[-1]["content"] += "\n\n" + message["text"]
        else:
            turns.append({"role": message["role"], "content": message["text"]})
    if not turns or turns[-1]["role"] != "user":
        turns.append({"role": "user", "content": NO_TEXT})
    documents = _documents(inputs)
    state = {"stl": stl or "нет", "документы": "приложены" if documents else "нет"}
    turns[-1]["content"] = (
        f"<state>\n{json.dumps(state, ensure_ascii=False)}\n</state>\n\n"
        f"<documents>\n{documents}\n</documents>\n\n"
        f"<messages>\n{turns[-1]['content'].strip() or NO_TEXT}\n</messages>"
    )
    return [{"role": "system", "content": system}, *turns]


def _documents(inputs: Inputs) -> str:
    files: dict[str, list[str]] = {}
    for page in inputs.documents:
        files.setdefault(page.filename, []).append(page.text)
    return "\n\n".join(
        f"{name}\n{chr(10).join(pages).strip()[:DOCUMENT_CHARS]}" for name, pages in files.items()
    ).strip()


def started(tool_calls: list[dict[str, Any]]) -> bool:
    return called(tool_calls, START) is not None


def called(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """The arguments of the first call of the tool, None when it was not called."""
    for call in tool_calls:
        function = call.get("function", {})
        if function.get("name") == name:
            arguments = json_repair.loads(function.get("arguments") or "{}")
            return arguments if isinstance(arguments, dict) else {}
    return None


def clean(text: str) -> str:
    """The chat shows plain text without dashes and colons, ending without a full stop."""
    text = _CJK.sub("", text)
    text = re.sub(r"\*\*|__|^#+\s*", "", text, flags=re.M)
    text = re.sub(r"\s+[—–]\s+", ", ", text)
    text = re.sub(r"\s*:[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"(?<=[^\d\s]):(?=\s)", ",", text)
    return text.strip().removesuffix(".")
