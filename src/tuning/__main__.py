"""CLI: python -m tuning select --card card.json --stl part.stl [--state s.json --verdict v.json]."""

import argparse
import sys

from tuning.errors import TuningError
from tuning.geometry import StlError, extract_features
from tuning.select import select_parameters
from tuning.serialization import dumps, load_json_file


def _parser():
    parser = argparse.ArgumentParser(prog="python -m tuning")
    commands = parser.add_subparsers(dest="command")
    select = commands.add_parser("select", help="choose print parameters for a task card and an STL")
    select.add_argument("--card", required=True, help="task_card/0 JSON file")
    select.add_argument("--stl", required=True, help="model to analyse")
    select.add_argument("--state", help="state JSON returned by the previous call")
    select.add_argument("--verdict", help="verdict/0 JSON file from the validator")
    select.add_argument("--strategy", default="m0", help="strategy id (default: m0)")
    select.add_argument("--seed", type=int, default=1)
    select.add_argument("--max-iterations", type=int, default=3, help="validator call budget N")
    select.add_argument("--materials-dir", help="STE Slicer resources/materials (or env STE_MATERIALS_DIR)")
    select.add_argument("--state-out", help="write the new state to this file")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command != "select":
        _parser().print_help(sys.stderr)
        return 2
    config = {
        "strategy": args.strategy,
        "seed": args.seed,
        "max_iterations": args.max_iterations,
        "materials_dir": args.materials_dir,
    }
    try:
        param_set, state = select_parameters(
            load_json_file(args.card),
            extract_features(args.stl),
            state=load_json_file(args.state) if args.state else None,
            verdict=load_json_file(args.verdict) if args.verdict else None,
            config=config,
        )
    except (TuningError, StlError, OSError, ValueError) as error:
        sys.stderr.write("error: %s\n" % error)
        return 2
    if args.state_out:
        with open(args.state_out, "w", encoding="utf-8") as stream:
            stream.write(dumps(state))
    sys.stdout.write(dumps(param_set) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
