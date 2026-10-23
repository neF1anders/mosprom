import json
import os
import subprocess
import sys

import pytest
from materials_factory import write_materials
from stl_factory import cube, frustum, write_binary

REPOSITORY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="session")
def materials_dir(tmp_path_factory):
    return write_materials(tmp_path_factory.mktemp("catalog") / "materials")


@pytest.fixture
def run_tuning(materials_dir):
    """Run the CLI as a real process; returns (exit code, stdout, stderr)."""

    def run(*args):
        environment = dict(os.environ, PYTHONPATH=os.path.join(REPOSITORY, "src"))
        process = subprocess.run(
            [sys.executable, "-m", "tuning"] + list(args) + ["--materials-dir", materials_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            cwd=REPOSITORY,
        )
        return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")

    return run


@pytest.fixture
def write_card(tmp_path):
    def write(**fields):
        card = {"schema": "task_card/0", "status": "ready", "inputs": {"text": "test part"}}
        card.update(fields)
        path = tmp_path / "card.json"
        path.write_text(json.dumps(card), encoding="utf-8")
        return str(path)

    return write


@pytest.fixture
def mushroom_stl(tmp_path):
    path = tmp_path / "mushroom.stl"
    write_binary(path, frustum(5, 15, 5))
    return str(path)


@pytest.fixture
def block_stl(tmp_path):
    path = tmp_path / "block.stl"
    write_binary(path, cube(20))
    return str(path)


@pytest.fixture
def tall_stl(tmp_path):
    path = tmp_path / "tall.stl"
    write_binary(path, [tuple((x, y, z * 28.0) for x, y, z in triangle) for triangle in cube(10)])
    return str(path)
