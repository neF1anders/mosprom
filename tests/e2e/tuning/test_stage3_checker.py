"""Acceptance by the stage-3 checker (validation/tools/check_parameter_set.py of the stage-3 branch).

The checker and the slicer resources belong to stage 3 and are not copied here: point VALIDATION_DIR at a
checkout or export of its `validation/` folder to run these tests.
"""

import json
import os
import subprocess
import sys

import pytest
from stage1_factory import constraint, feedback, handoff, report, requirement

VALIDATION_DIR = os.environ.get("VALIDATION_DIR")
pytestmark = pytest.mark.skipif(not VALIDATION_DIR, reason="stage-3 checker not available (set VALIDATION_DIR)")

CASES = {
    "classic_strong": (
        handoff(
            requirements=[requirement("high_stiffness", "да"), requirement("load_bearing", "циклическая нагрузка")],
            preferences=["прочность"],
        ),
        None,
    ),
    "classic_fast": (handoff(preferences=["быстро"]), None),
    "cylindrical_full": (handoff(requirements=[requirement("printing_mode", "cylindrical_full")]), None),
    "cylindrical": (handoff(requirements=[requirement("printing_mode", "cylindrical")], stl_report=report()), None),
    "second_iteration": (handoff(), feedback(constraint("C1", "infill_sparse_density", "eq", 15))),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_parameter_set_passes_the_stage3_checker_without_warnings(select, tmp_path, name):
    payload, review = CASES[name]
    code, parameter_set, err = select(payload, review)
    assert code == 0, err
    path = tmp_path / "parameter_set.json"
    path.write_text(json.dumps(parameter_set, ensure_ascii=False), encoding="utf-8")
    checker = subprocess.run(
        [
            sys.executable,
            os.path.join(VALIDATION_DIR, "tools", "check_parameter_set.py"),
            os.path.join(VALIDATION_DIR, "resources", "ste_5.2.4"),
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = checker.stdout.decode("utf-8")
    assert checker.returncode == 0, output
    assert "ошибок: 0, предупреждений: 0" in output, output
