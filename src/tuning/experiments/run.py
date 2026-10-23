"""Batch runner: strategies x worlds x cases x seeds against the validator stub, in process."""

import argparse
import glob
import json
import os
import statistics
import sys
import time
from typing import Any  # noqa: F401  (used in type comments)

from tuning.experiments.stub_validator import WORLDS, StubValidator
from tuning.geometry import extract_features
from tuning.hard_rules import hard_rule_violations
from tuning.select import prepare, select_parameters
from tuning.serialization import load_json_file


def run_loop(card, geometry, validator, config):
    # type: (dict, dict, Any, dict) -> tuple
    """Drive select_parameters with the validator until the module stops proposing; returns (param_set, calls)."""
    validator.restart()
    param_set, state = select_parameters(card, geometry, config=config)
    calls = 0
    while param_set["status"] == "proposed":
        if calls >= config["max_iterations"]:
            raise AssertionError("module still proposes after %d validator calls" % calls)
        verdict = validator.verdict(param_set)
        calls += 1
        param_set, state = select_parameters(card, geometry, state=state, verdict=verdict, config=config)
    return param_set, calls


def run_cell(strategy, world, case, seed, context, config):
    # type: (str, str, str, int, Any, dict) -> tuple
    """One experiment cell; returns (record, canonical final param_set JSON)."""
    card, geometry, preparation, validator = context
    cell_config = dict(config, strategy=strategy, seed=seed)
    started = time.time()
    param_set, calls = run_loop(card, geometry, validator, cell_config)
    elapsed = time.time() - started
    regret = None
    if param_set["status"] == "final":
        regret = (validator.metrics(validator.values_of(param_set))["T"] - validator.t_opt) / validator.t_opt
    record = {
        "strategy": strategy,
        "world": world,
        "case": case,
        "seed": seed,
        "n": config["max_iterations"],
        "status": param_set["status"],
        "validator_calls": calls,
        "regret": regret,
        "hard_violations": len(hard_rule_violations(param_set, preparation.profile, preparation.material)),
        "t_opt": validator.t_opt,
        "wall_time_s": round(elapsed, 4),
    }
    return record, json.dumps(param_set, sort_keys=True)


def load_cases(directory):
    # type: (str) -> list
    """[(name, card)] for every card json in the directory, sorted by file name."""
    paths = sorted(glob.glob(os.path.join(directory, "*.json")))
    if not paths:
        raise SystemExit("no card json files in %s" % directory)
    return [(os.path.splitext(os.path.basename(path))[0], load_json_file(path)) for path in paths]


def _mean(values):
    return "%.3f" % statistics.mean(values) if values else "-"


def _median(values):
    return "%.3f" % statistics.median(values) if values else "-"


def _stability(records, field):
    # type: (list, Any) -> str
    """Mean over cases of the population std over seeds of field(record)."""
    by_case = {}  # type: dict
    for record in records:
        by_case.setdefault(record["case"], []).append(field(record))
    return "%.3f" % statistics.mean(statistics.pstdev(values) for values in by_case.values())


def summary_rows(records, strategies, worlds):
    # type: (list, list, list) -> list
    rows = []
    for strategy in strategies:
        for world in worlds:
            cells = [r for r in records if r["strategy"] == strategy and r["world"] == world]
            finals = [r for r in cells if r["status"] == "final"]
            rows.append(
                [
                    strategy,
                    world,
                    str(len(cells)),
                    "%.1f" % (100.0 * len(finals) / len(cells)),
                    _mean([r["validator_calls"] for r in finals]),
                    _median([r["validator_calls"] for r in finals]),
                    _mean([r["regret"] for r in finals]),
                    _median([r["regret"] for r in finals]),
                    str(sum(r["hard_violations"] for r in cells)),
                    _stability(cells, lambda r: 1.0 if r["status"] == "final" else 0.0),
                    _stability(cells, lambda r: float(r["validator_calls"])),
                    "%.3f" % statistics.mean(r["wall_time_s"] for r in cells),
                ]
            )
    return rows


def case_rows(records, strategies, worlds, case_names):
    # type: (list, list, list, list) -> list
    rows = []
    for strategy in strategies:
        for world in worlds:
            row = [strategy, world]
            for case in case_names:
                cells = [r for r in records if (r["strategy"], r["world"], r["case"]) == (strategy, world, case)]
                row.append("%.0f" % (100.0 * sum(r["status"] == "final" for r in cells) / len(cells)))
            rows.append(row)
    return rows


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_summary(args, case_names, records, determinism):
    # type: (Any, list, list, dict) -> str
    strategies, worlds = args.strategies.split(","), args.worlds.split(",")
    parts = [
        "# Experiment summary",
        "",
        "- strategies: %s" % ", ".join(strategies),
        "- worlds: %s" % ", ".join(worlds),
        "- seeds: 1..%d" % args.seeds,
        "- N (validator calls): %d" % args.n,
        "- cases: %s" % ", ".join(case_names),
        "",
        "## Per strategy and world (aggregated over cases and seeds)",
        "",
        _table(
            [
                "strategy",
                "world",
                "cells",
                "final %",
                "calls mean",
                "calls median",
                "regret mean",
                "regret median",
                "hard violations",
                "std final",
                "std calls",
                "wall s/cell",
            ],
            summary_rows(records, strategies, worlds),
        ),
        "",
        "## Final rate % per case",
        "",
        _table(["strategy", "world"] + case_names, case_rows(records, strategies, worlds, case_names)),
        "",
        "## Determinism (seed 1 run twice, byte-identical final param_set)",
        "",
        _table(
            ["strategy", "world", "identical %"],
            [
                [s, w, "%.0f" % (100.0 * determinism[(s, w)][0] / determinism[(s, w)][1])]
                for s in strategies
                for w in worlds
            ],
        ),
        "",
    ]
    return "\n".join(parts)


def _parser():
    parser = argparse.ArgumentParser(prog="python -m tuning.experiments.run")
    parser.add_argument("--strategies", required=True, help="comma separated strategy ids")
    parser.add_argument("--worlds", required=True, help="comma separated subset of %s" % ",".join(WORLDS))
    parser.add_argument("--seeds", type=int, required=True, help="seeds 1..K")
    parser.add_argument("--cases", required=True, help="directory of task card jsons")
    parser.add_argument("--materials-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--n", type=int, default=3, help="validator call budget N")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    config = {"max_iterations": args.n, "materials_dir": args.materials_dir}
    strategies, worlds = args.strategies.split(","), args.worlds.split(",")
    cases, geometries = load_cases(args.cases), {}
    prepared = {}
    for name, card in cases:
        path = card["inputs"]["files"][0]["path"]
        if path not in geometries:
            geometries[path] = extract_features(path)
        prepared[name] = (card, geometries[path], prepare(card, geometries[path], config))
    records, determinism = [], {(s, w): [0, 0] for s in strategies for w in worlds}
    for world in worlds:
        for name, card in cases:
            card, geometry, preparation = prepared[name]
            for seed in range(1, args.seeds + 1):
                context = (card, geometry, preparation, StubValidator(world, seed, preparation, geometry, card))
                for strategy in strategies:
                    record, final_json = run_cell(strategy, world, name, seed, context, config)
                    records.append(record)
                    if seed == 1:
                        _, again = run_cell(strategy, world, name, seed, context, config)
                        determinism[(strategy, world)][0] += int(again == final_json)
                        determinism[(strategy, world)][1] += 1
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "cells.jsonl"), "w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    summary = render_summary(args, [name for name, _ in cases], records, determinism)
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as stream:
        stream.write(summary)
    sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
