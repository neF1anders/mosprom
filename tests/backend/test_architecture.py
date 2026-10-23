import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture
ROOT = Path("src/backend")


@pytest.mark.parametrize(
    ("folder", "forbidden"),
    [
        ("api/routes", ("sqlalchemy", "asyncpg", "infrastructure")),
        ("services", ("sqlalchemy", "asyncpg", "fastapi", "infrastructure")),
        ("domain", ("sqlalchemy", "asyncpg", "fastapi", "httpx", "infrastructure")),
        ("ports", ("sqlalchemy", "asyncpg", "fastapi", "infrastructure")),
        ("infrastructure", ("api.routes", "services")),
    ],
)
def test_A01_import_boundaries(folder, forbidden):
    files = list((ROOT / folder).glob("*.py"))
    assert any(p.stat().st_size for p in files), f"{folder} has no implementation"
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(
                part in name.split(".") or part in name for name in names for part in forbidden
            ), (path, names)


def test_A01_worker_calls_shared_pipeline():
    text = (ROOT / "worker.py").read_text()
    assert "container.pipeline.run(work)" in text
    assert "select(" not in text


def test_A01_application_branch_nesting_at_most_two():
    def visit(node, depth=0):
        current = depth + isinstance(node, ast.If)
        assert current <= 2, (path, node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    for folder in ["domain", "services"]:
        for path in (ROOT / folder).glob("*.py"):
            visit(ast.parse(path.read_text()))
