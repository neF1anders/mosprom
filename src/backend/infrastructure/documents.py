"""Untrusted document parsing runs only in the resource-limited process runner."""

from __future__ import annotations

import signal
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from ..domain.errors import AppError
from ..domain.limits import LIMITS, InputLimits


def inspect_document(path: Path, kind: str, limits: InputLimits | None = None) -> dict[str, Any]:
    limits = limits or InputLimits()
    if kind not in LIMITS:
        raise AppError("Формат файла не поддерживается", "unsupported_type")
    size = path.stat().st_size
    if not size:
        raise AppError("Файл пуст", "empty_file")
    if size > limits.file_mib(kind) * 1024 * 1024:
        raise AppError("Файл превышает допустимый размер", "file_too_large", 413)
    parsers = {
        "txt": _text,
        "md": _text,
        "pdf": _pdf,
        "docx": _docx,
        "png": _image,
        "jpg": _image,
        "jpeg": _image,
        "stl": _stl,
    }
    try:
        return parsers[kind](path, limits)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "Не удалось прочитать файл, проверьте формат и целостность", "document_corrupt"
        ) from exc


def _fragment(text: str, page: int, **extra: Any) -> dict[str, Any]:
    return {"text": text, "page": page, "method": "text", "uncertain": False, **extra}


def _text(path: Path, limits: InputLimits) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if "\x00" in text:
        raise AppError("Вместо текста обнаружены двоичные данные", "type_mismatch")
    return {"fragments": [_fragment(text, 1)], "artifacts": []}


def _docx(path: Path, limits: InputLimits) -> dict[str, Any]:
    from docx import Document
    from docx.table import Table

    try:
        with ZipFile(path) as archive:
            if (
                sum(i.file_size for i in archive.infolist())
                > limits.expanded_docx_mib * 1024 * 1024
            ):
                raise AppError("Распакованный DOCX превышает 100 MiB", "expanded_limit", 413)
            if "word/document.xml" not in archive.namelist():
                raise AppError("Файл не является DOCX", "type_mismatch")
    except BadZipFile as exc:
        raise AppError("Повреждён DOCX", "document_corrupt") from exc
    doc = Document(str(path))
    blocks: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            blocks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
        else:
            blocks.append(block.text)
    return {"fragments": [_fragment("\n".join(blocks), 1)], "artifacts": []}


def _ocr(image, timeout: float = 30) -> tuple[str, bool]:
    import pytesseract

    data = pytesseract.image_to_data(
        image, lang="rus+eng", output_type=pytesseract.Output.DICT, timeout=timeout
    )
    words = [
        (word, float(score)) for word, score in zip(data["text"], data["conf"]) if word.strip()
    ]
    uncertain = any(score < 85 and any(c.isdigit() for c in word) for word, score in words)
    return " ".join(word for word, _ in words), uncertain


def _pdf(path: Path, limits: InputLimits) -> dict[str, Any]:
    import pypdfium2
    from pypdf import PdfReader

    with path.open("rb") as stream:
        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
            raise AppError("Файл не является PDF", "type_mismatch")
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise AppError("PDF защищён паролем, загрузите незашифрованную копию", "pdf_encrypted")
    if len(reader.pages) > limits.pdf_pages:
        raise AppError(f"В PDF больше {limits.pdf_pages} страниц", "page_limit", 413)
    fragments, artifacts = [], []
    with pypdfium2.PdfDocument(path) as rendered:
        for number, page in enumerate(reader.pages, 1):
            with page_deadline(limits.page_seconds):
                fragment, artifact = _pdf_page(path, number, page, rendered, limits)
            fragments.append(fragment)
            if artifact:
                artifacts.append(artifact)
    return {"fragments": fragments, "artifacts": artifacts}


@contextmanager
def page_deadline(seconds: float):
    def expired(signum, frame):
        raise AppError(f"Страница PDF не обработана за {seconds:g} секунд", "page_timeout", 503)

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _thumbnail(image, path: Path, suffix: str) -> str:
    artifact = f"{path.name}-{suffix}.png"
    preview = image.convert("RGB")
    preview.thumbnail((1024, 1024))
    preview.save(path.parent / artifact)
    return artifact


def _pdf_page(path, number, page, rendered, limits):
    text = page.extract_text(extraction_mode="layout") or ""
    # Image XObjects can contain extra requirements on a page with a text layer.
    if len(text.strip()) >= 30 and not page.images:
        return _fragment(text, number), None
    pdf_page = rendered[number - 1]
    width, height = pdf_page.get_size()
    if width * height * 4 > limits.image_pixels:
        raise AppError("Страница PDF превышает лимит рендера 25 мегапикселей", "pixel_limit", 413)
    image = pdf_page.render(scale=2).to_pil()
    artifact = _thumbnail(image, path, f"page-{number}")
    recognized, uncertain = _ocr(image, limits.page_seconds)
    combined = text + "\n" + recognized if text.strip() else recognized
    return _fragment(
        combined, number, method="ocr", uncertain=uncertain or not combined.strip(), image=artifact
    ), artifact


def _image(path: Path, limits: InputLimits) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG"}:
            raise AppError("Изображение должно быть JPEG или PNG", "type_mismatch")
        if image.width * image.height > limits.image_pixels:
            raise AppError("Изображение превышает 25 мегапикселей", "pixel_limit", 413)
        image.verify()
    with Image.open(path) as image:
        text, uncertain = _ocr(image, limits.page_seconds)
        artifact = _thumbnail(image, path, "preview")
    return {
        "fragments": [_fragment(text, 1, method="ocr", uncertain=uncertain, image=artifact)],
        "artifacts": [artifact],
    }


def _stl(path: Path, limits: InputLimits) -> dict[str, Any]:
    from src.mesh_analysis import read_stl

    try:
        read_stl(path, limits.stl_mib * 1024 * 1024, limits.triangles)
    except ValueError as exc:
        raise AppError(str(exc), "invalid_stl") from exc
    return {"fragments": [], "artifacts": []}
