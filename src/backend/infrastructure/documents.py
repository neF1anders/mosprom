"""Untrusted document parsing runs only in the resource-limited process runner."""

from __future__ import annotations

import signal
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from ..domain.errors import AppError
from ..domain.limits import KINDS, InputLimits

FULL_PAGE_PIXELS = 4096


def inspect_document(path: Path, kind: str, limits: InputLimits | None = None) -> dict[str, Any]:
    limits = limits or InputLimits()
    if kind not in KINDS - {"stl"}:
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
    }
    try:
        return parsers[kind](path, limits)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "Не удалось прочитать файл, проверьте формат и целостность", "document_corrupt"
        ) from exc


def _fragment(text: str, page: int, image: str | None = None) -> dict[str, Any]:
    return {"text": text, "page": page, "image": image}


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
    fragments, artifacts = [_fragment("\n".join(blocks), 1)], []
    # Drawings embedded in the document are read by the model like scanned pages.
    for number, part in enumerate(_docx_images(doc), 2):
        artifact = _image_artifact(_open_image(part.blob, limits), path, f"figure-{number}")
        fragments.append(_fragment("", number, artifact))
        artifacts.append(artifact)
    return {"fragments": fragments, "artifacts": artifacts}


def _docx_images(doc) -> list:
    return [rel.target_part for rel in doc.part.rels.values() if "image" in rel.reltype]


def _open_image(blob: bytes, limits: InputLimits):
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(blob))
    if image.width * image.height > limits.image_pixels:
        raise AppError("Рисунок в документе превышает 25 мегапикселей", "pixel_limit", 413)
    image.load()
    return image


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


def _image_artifact(image, path: Path, suffix: str) -> str:
    """Full-resolution page; the request downsizes it, view_page crops it."""
    artifact = f"{path.name}-{suffix}.png"
    page = image.convert("RGB")
    page.thumbnail((FULL_PAGE_PIXELS, FULL_PAGE_PIXELS))
    page.save(path.parent / artifact)
    return artifact


def _pdf_page(path, number, page, rendered, limits):
    text = page.extract_text(extraction_mode="layout") or ""
    pdf_page = rendered[number - 1]
    width, height = pdf_page.get_size()
    # Render as sharply as the pixel budget allows; large drawings get a smaller scale.
    scale = min(3.0, (limits.image_pixels / (width * height)) ** 0.5)
    image = pdf_page.render(scale=scale).to_pil()
    artifact = _image_artifact(image, path, f"page-{number}")
    return _fragment(text, number, artifact), artifact


def _image(path: Path, limits: InputLimits) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG"}:
            raise AppError("Изображение должно быть JPEG или PNG", "type_mismatch")
        if image.width * image.height > limits.image_pixels:
            raise AppError("Изображение превышает 25 мегапикселей", "pixel_limit", 413)
        image.verify()
    with Image.open(path) as image:
        artifact = _image_artifact(image, path, "preview")
    return {"fragments": [_fragment("", 1, artifact)], "artifacts": [artifact]}
