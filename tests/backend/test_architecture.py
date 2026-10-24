import ast
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.architecture
ROOT = Path("src/backend")
# Selection and its check are pure: they get the card and the catalog and return values.
STAGE_CORE = (
    "sqlalchemy",
    "psycopg",
    "fastapi",
    "httpx",
    "infrastructure",
    "agents",
    "services",
    "pipeline",
)


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
        ("api/routes", ("sqlalchemy", "psycopg", "infrastructure")),
        ("services", ("sqlalchemy", "psycopg", "fastapi", "infrastructure")),
        ("agents", ("sqlalchemy", "psycopg", "fastapi", "infrastructure", "httpx")),
        ("domain", ("sqlalchemy", "psycopg", "fastapi", "httpx", "infrastructure", "agents")),
        ("domain", ("pipeline", "services", "tuning", "validation")),
        ("pipeline", ("sqlalchemy", "psycopg", "fastapi", "httpx", "infrastructure", "agents")),
        ("ports", ("sqlalchemy", "psycopg", "fastapi", "infrastructure")),
        ("infrastructure", ("api.routes", "services", "agents")),
        ("validation", STAGE_CORE),
        ("tuning", STAGE_CORE),
        ("slicing", STAGE_CORE),
    ],
)
def test_A01_import_boundaries(folder, forbidden):
    files = list((ROOT / folder).rglob("*.py"))
    assert any(p.stat().st_size for p in files), f"{folder} has no implementation"
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = _imports(node)
            assert not any(
                part in name.split(".") or part in name for name in names for part in forbidden
            ), (path, names)


def test_A01_worker_runs_the_shared_stage_one():
    text = (ROOT / "tasks.py").read_text()
    assert "container.stage1.run(job_id, revision)" in text
    assert "container.pipeline.run(job_id, revision)" in text
    assert "select(" not in (ROOT / "worker.py").read_text()


def test_A01_application_branch_nesting_at_most_two():
    """Statements nest at most two deep; a conditional expression never holds another one."""

    def visit(node, depth=0, inline=False):
        current = depth + isinstance(node, ast.If)
        assert current <= 2, (path, node.lineno)
        assert not (inline and isinstance(node, ast.IfExp)), (path, node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, current, inline or isinstance(node, ast.IfExp))

    for folder in [
        "domain",
        "services",
        "agents",
        "api",
        "infrastructure",
        "pipeline",
        "validation",
        "tuning",
    ]:
        for path in (ROOT / folder).rglob("*.py"):
            visit(ast.parse(path.read_text()))
