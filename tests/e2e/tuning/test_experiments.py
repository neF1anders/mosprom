import json
import os
import subprocess
import sys

import pytest
from conftest import REPOSITORY

from tuning.experiments import oracle
from tuning.experiments.run import run_loop
from tuning.experiments.stub_validator import WORLDS, StubValidator
from tuning.geometry import extract_features
from tuning.select import prepare, render_points

CARD = {
    "schema": "task_card/0",
    "status": "ready",
    "inputs": {"text": "test part"},
    "part": {"load": "cyclic"},
    "preferences": {"priority": ["strength", "accuracy"]},
    "requirements": [
        {"id": "R1", "kind": "x", "key": "high_stiffness", "value": True, "hard": True, "source": "user"},
        {"id": "R2", "kind": "x", "key": "dimensional_tol_mm", "value": 0.15, "hard": False, "source": "user"},
    ],
}


@pytest.fixture
def setup(materials_dir, block_stl):
    geometry = extract_features(block_stl)
    return CARD, geometry, prepare(CARD, geometry, {"materials_dir": materials_dir})


def make_validator(setup, world, seed=1):
    card, geometry, preparation = setup
    return StubValidator(world, seed, preparation, geometry, card)


def lowest_point(setup):
    plan = setup[2].plan["params"]
    return render_points(setup[2], {param_id: entry["lo"] for param_id, entry in plan.items()})


def test_validator_is_deterministic_and_worlds_differ(setup):
    param_set = lowest_point(setup)
    for world in WORLDS:
        assert make_validator(setup, world).verdict(param_set) == make_validator(setup, world).verdict(param_set)
    plan = setup[2].plan["params"]
    middle = render_points(setup[2], {param_id: (e["lo"] + e["hi"]) / 2.0 for param_id, e in plan.items()})
    values = make_validator(setup, "w1").values_of(middle)
    metrics = [make_validator(setup, world).metrics(values) for world in WORLDS]
    assert metrics[0] != metrics[1] and metrics[1] != metrics[2]
    assert make_validator(setup, "w2", seed=1).metrics(values) != make_validator(setup, "w2", seed=2).metrics(values)


def test_severity_only_in_noise_free_worlds(setup):
    param_set = lowest_point(setup)
    for world, expects_severity in (("w1", True), ("w2", True), ("w3", False)):
        verdict = make_validator(setup, world).verdict(param_set)
        assert not verdict["ok"] and verdict["issues"]
        assert all(("severity" in issue) == expects_severity for issue in verdict["issues"])
    t_issues = [i for i in make_validator(setup, "w1").verdict(param_set)["issues"] if i["signal"] == "too_costly"]
    assert all("requirement_id" not in issue and not issue["hard"] for issue in t_issues)


@pytest.mark.parametrize("world", WORLDS)
def test_oracle_point_is_feasible_and_not_worse_than_rule_start(setup, world):
    validator = make_validator(setup, world)
    preparation = setup[2]
    rows = oracle.evaluate_grid(preparation, validator.unit_metrics)
    max_s, max_q = oracle.maxima(rows)
    assert validator.s_min <= 0.85 * max_s + 1e-12 and validator.q_min <= 0.85 * max_q + 1e-12
    optimum = validator.metrics(validator.opt_values)
    assert optimum["S"] >= validator.s_min and optimum["Q"] >= validator.q_min
    assert optimum["T"] == pytest.approx(validator.t_opt)
    start = {
        param_id: preparation.params[param_id].value_at(min(max(entry["t0"], entry["lo"]), entry["hi"]))
        for param_id, entry in preparation.plan["params"].items()
    }
    metrics = validator.metrics(start)
    if metrics["S"] >= validator.s_min and metrics["Q"] >= validator.q_min:
        assert validator.t_opt <= metrics["T"] + 1e-12


@pytest.mark.parametrize("world", WORLDS)
@pytest.mark.parametrize("strategy", ["m0", "m1"])
def test_loop_ends_in_a_terminal_status_within_budget(setup, materials_dir, world, strategy):
    card, geometry, _ = setup
    for seed in (1, 2, 3):
        config = {"strategy": strategy, "seed": seed, "max_iterations": 3, "materials_dir": materials_dir}
        param_set, calls = run_loop(card, geometry, make_validator(setup, world, seed), config)
        assert param_set["status"] in ("final", "exhausted", "infeasible")
        assert calls <= 3


def test_runner_end_to_end_is_deterministic(materials_dir, block_stl, mushroom_stl, tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    for name, stl in (("block", block_stl), ("mushroom", mushroom_stl)):
        card = dict(CARD, inputs={"text": name, "files": [{"path": stl, "kind": "stl"}]})
        (cases / (name + ".json")).write_text(json.dumps(card), encoding="utf-8")

    def run(out):
        environment = dict(os.environ, PYTHONPATH=os.path.join(REPOSITORY, "src"))
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "tuning.experiments.run",
                "--strategies",
                "m0,m1",
                "--worlds",
                "w1",
                "--seeds",
                "2",
                "--cases",
                str(cases),
                "--materials-dir",
                materials_dir,
                "--out",
                str(out),
                "--n",
                "3",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            cwd=REPOSITORY,
        )
        assert process.returncode == 0, process.stderr.decode("utf-8")
        records = [json.loads(line) for line in (out / "cells.jsonl").read_text(encoding="utf-8").splitlines()]
        for record in records:
            del record["wall_time_s"]
        return records

    first, second = run(tmp_path / "a"), run(tmp_path / "b")
    assert first == second and len(first) == 2 * 2 * 2
    assert sum(record["hard_violations"] for record in first) == 0
    summary = (tmp_path / "a" / "summary.md").read_text(encoding="utf-8")
    assert "Determinism" in summary and "| m1 | w1 | 100 |" in summary
