import ast
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.architecture
ROOT = Path("src/backend")


def _imports(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def test_runtime_dependencies_cover_lazy_production_imports():
    config = tomllib.loads(Path("pyproject.toml").read_text())
    packages = {Requirement(line).name.lower() for line in config["project"]["dependencies"]}
    distributions = {"PIL": "pillow", "docx": "python-docx", "mpl_toolkits": "matplotlib"}
    for path in [*ROOT.rglob("*.py"), Path("src/mesh_analysis.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                continue
            external = (
                {name.split(".")[0] for name in _imports(node)} - sys.stdlib_module_names - {"src"}
            )
            for name in external:
                package = distributions.get(name, name.lower().replace("_", "-"))
                assert package in packages, (path, node.lineno, package)


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
            names = _imports(node)
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
