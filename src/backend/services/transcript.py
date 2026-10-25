"""The chat of a finished project as pictures, for the folder the user keeps.

The pictures are drawn here rather than shot in a browser: the chat may be closed when the
project ends. The user's messages stand on the right and the assistant's on the left, as in
the chat; a long chat goes on to the next picture.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
WIDTH = 1080
MARGIN = 40
BUBBLE = 800
PAD = 20
GAP = 26
TEXT = 22
SMALL = 17
LINE = 32
# A picture taller than this is hard to read; the rest of the chat goes to the next one.
PAGE = 3200
# Fewer lines than this left at the bottom of a picture start the message on the next one.
FEW = 4
BACKGROUND, TEXT_COLOR, MUTED = "#f4f5f7", "#1d2228", "#6b7380"
USER_FILL, ASSISTANT_FILL, BORDER = "#dce9ff", "#ffffff", "#e1e4e9"
LABELS = {
    ("user", "answers"): "Ответы на вопросы",
    ("assistant", "report"): "Итоговый отчёт",
    ("user", ""): "Вы",
    ("assistant", ""): "Ассистент",
}


@dataclass(frozen=True)
class Entry:
    role: str
    label: str
    lines: list[tuple[str, bool]]


@dataclass(frozen=True)
class Block:
    """A bubble, or the part of a long one that fits a picture."""

    role: str
    label: str
    rows: list[tuple[str, bool]]

    @property
    def height(self) -> int:
        return SMALL + 10 + 2 * PAD + LINE * len(self.rows)


def entries(messages: list[dict[str, Any]], names: dict[str, str]) -> list[Entry]:
    """The messages as the chat shows them, with the files each one brought."""
    shown = []
    for message in messages:
        role = "user" if message.get("role") == "user" else "assistant"
        kind = str(message.get("kind") or "")
        label = LABELS.get((role, kind)) or LABELS[(role, "")]
        lines = plain(str(message.get("text") or ""))
        files = [names[i] for i in message.get("attachment_ids") or [] if i in names]
        if files:
            lines.append((f"Файлы {', '.join(files)}", False))
        if any(text for text, _ in lines):
            shown.append(Entry(role, label, lines))
    return shown


def plain(text: str) -> list[tuple[str, bool]]:
    """Markdown as plain lines; a heading is kept as a bold line."""
    lines = []
    for raw in text.strip().splitlines():
        line, bold = raw.rstrip(), False
        heading = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if heading:
            line, bold = heading.group(1), True
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        lines.append((line, bold))
    return lines


def render(title: str, shown: list[Entry], when: str) -> list[bytes]:
    """PNG pictures of the chat, the first one headed by the project's name."""
    header = [(f"Переписка по проекту «{title}»", True), (when, False)]
    pages: list[list[Block]] = [[]]
    used = _header_height(header)
    for entry in shown:
        rows, label = _rows(entry), entry.label
        while rows:
            fit = (PAGE - used - GAP - SMALL - 10 - 2 * PAD - MARGIN) // LINE
            # A long message fills the rest of the picture and goes on in the next one; a
            # bubble of a few lines is not cut off at the bottom.
            if pages[-1] and fit < min(len(rows), FEW):
                pages.append([])
                used = MARGIN
                continue
            block = Block(entry.role, label, rows[:fit])
            pages[-1].append(block)
            used += GAP + block.height
            rows, label = rows[fit:], f"{entry.label}, продолжение"
    return [_draw(blocks, header if number == 0 else []) for number, blocks in enumerate(pages)]


def _rows(entry: Entry) -> list[tuple[str, bool]]:
    return [
        (part, bold)
        for text, bold in entry.lines
        for part in wrap(text, _font(bold, TEXT), BUBBLE - 2 * PAD)
    ]


def wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Lines no wider than ``width``; a word longer than a line, a path say, breaks anywhere."""
    if not text.strip():
        return [""]
    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if font.getlength(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while font.getlength(word) > width:
            cut = len(word) - 1
            while cut > 1 and font.getlength(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    lines.append(current)
    return lines


def _header_height(header: list[tuple[str, bool]]) -> int:
    return MARGIN + LINE * len(header) + 10


def _draw(blocks: list[Block], header: list[tuple[str, bool]]) -> bytes:
    top = _header_height(header) if header else MARGIN
    height = top + sum(GAP + b.height for b in blocks) + MARGIN
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    y = MARGIN
    for text, bold in header:
        draw.text((MARGIN, y), text, font=_font(bold, TEXT), fill=TEXT_COLOR if bold else MUTED)
        y += LINE
    y = top
    for block in blocks:
        y += GAP
        fonts = [_font(bold, TEXT) for _, bold in block.rows]
        inner = max([int(f.getlength(t)) for f, (t, _) in zip(fonts, block.rows)] + [120])
        width = min(inner, BUBBLE - 2 * PAD) + 2 * PAD
        x = WIDTH - MARGIN - width if block.role == "user" else MARGIN
        label = _font(False, SMALL)
        label_x = x + width - int(label.getlength(block.label)) if block.role == "user" else x
        draw.text((label_x, y), block.label, font=label, fill=MUTED)
        top_of_bubble = y + SMALL + 10
        fill = USER_FILL if block.role == "user" else ASSISTANT_FILL
        outline = None if block.role == "user" else BORDER
        box = (x, top_of_bubble, x + width, y + block.height)
        draw.rounded_rectangle(box, radius=16, fill=fill, outline=outline)
        row_y = top_of_bubble + PAD
        for font, (text, _) in zip(fonts, block.rows):
            draw.text((x + PAD, row_y), text, font=font, fill=TEXT_COLOR)
            row_y += LINE
        y += block.height
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


@cache
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONTS / name), size)
