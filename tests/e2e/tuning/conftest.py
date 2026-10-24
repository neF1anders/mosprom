import json
import os
import subprocess
import sys

import pytest
from materials_factory import write_materials
from stage1_factory import write_handoff

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
def select(run_tuning, tmp_path):
    """select(handoff, feedback=None) -> (exit code, parameter_set or None, stderr)."""

    def run(payload, feedback=None):
        args = ["select", "--input", write_handoff(tmp_path / "handoff.json", payload)]
        if feedback is not None:
            path = tmp_path / "feedback.json"
            path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
            args += ["--feedback", str(path)]
        code, out, err = run_tuning(*args)
        return code, (json.loads(out) if code == 0 else None), err

    return run
