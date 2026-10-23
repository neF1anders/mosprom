from pathlib import Path

import pytest

from src.backend.domain.errors import AppError
from src.backend.infrastructure.documents import inspect_document

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name,pages", [("text.pdf", 1), ("scan.pdf", 1), ("mixed.pdf", 2)])
def test_T02_all_pdf_pages_are_covered(name, pages, tmp_path):
    target = tmp_path / "document"
    target.write_bytes((Path("tests/fixtures") / name).read_bytes())
    result = inspect_document(target, "pdf")
    assert len(result["fragments"]) == pages
    assert {f["page"] for f in result["fragments"]} == set(range(1, pages + 1))
    assert all("25" in f["text"] and "75" in f["text"] for f in result["fragments"])


@pytest.mark.parametrize(
    "name,code",
    [
        ("encrypted.pdf", "pdf_encrypted"),
        ("corrupt.pdf", "document_corrupt"),
        ("too-many-pages.pdf", "page_limit"),
    ],
)
def test_T02_distinct_pdf_errors(name, code):
    with pytest.raises(AppError) as exc:
        inspect_document(Path("tests/fixtures") / name, "pdf")
    assert exc.value.code == code
