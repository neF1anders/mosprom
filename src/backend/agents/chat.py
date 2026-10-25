"""Helpers of the agents that talk in the chat: tools from the prompt, calls and chat text.

An agent in the chat decides only by calling a tool, so the code reads the decision from the
call and never from the text. Its text reaches the chat as it is, so the rules of the chat
text are enforced here as well, not only asked for in the prompt.
"""

from __future__ import annotations

import re
from typing import Any

import json_repair

from .context import Inputs

# Enough of each document to judge what it describes, short enough for a quick reply.
DOCUMENT_CHARS = 6000
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def split_tool(
    text: str, name: str, parameters: dict[str, Any] | None = None
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


def documents(inputs: Inputs) -> str:
    """The start of each document, enough to tell what part it describes."""
    files: dict[str, list[str]] = {}
    for page in inputs.documents:
        files.setdefault(page.filename, []).append(page.text)
    return "\n\n".join(
        f"{name}\n{chr(10).join(pages).strip()[:DOCUMENT_CHARS]}" for name, pages in files.items()
    ).strip()


def called(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """The arguments of the first call of the tool, None when it was not called."""
    for call in tool_calls:
        function = call.get("function", {})
        if function.get("name") == name:
            arguments = json_repair.loads(function.get("arguments") or "{}")
            return arguments if isinstance(arguments, dict) else {}
    return None


def chat_text(text: str) -> str:
    """Markdown as the chat shows it: no dashes or colons, no full stop at the end."""
    text = _CJK.sub("", text)
    text = re.sub(r"\s*:[ \t]*$", "", text, flags=re.M)
    # A colon before a space is punctuation; one inside a time like 10:30 stays.
    text = re.sub(r"(?<=\S):(?=\s)", ",", text)
    # A dash that opens a line of dialogue goes; one inside a sentence becomes a comma.
    text = re.sub(r"(?m)^([ \t]*)[—–][ \t]*", r"\1", text)
    text = re.sub(r",?\s+[—–]\s+", ", ", text)
    # One inside a range or a word, like 3–6 %, is a hyphen.
    text = re.sub(r"(?<=\w)[—–](?=\w)", "-", text)
    return text.strip().removesuffix(".")
