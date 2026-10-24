"""CLI: python -m tuning select --input handoff.json [--feedback feedback.json] --materials-dir DIR."""

import argparse
import sys

from tuning.errors import TuningError
from tuning.select import select_parameters
from tuning.serialization import dumps, load_json_file


def _parser():
    parser = argparse.ArgumentParser(prog="python -m tuning")
    commands = parser.add_subparsers(dest="command")
    select = commands.add_parser("select", help="choose print parameters for a stage-1 handoff")
    select.add_argument("--input", required=True, help="stage-1 handoff JSON: {idempotency_key, card} (task card v1.1)")
    select.add_argument("--feedback", help="stage3.feedback JSON on the first proposal (second iteration)")
    select.add_argument("--materials-dir", help="STE Slicer resources/materials (or env STE_MATERIALS_DIR)")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command != "select":
        _parser().print_help(sys.stderr)
        return 2
    try:
        feedback = load_json_file(args.feedback) if args.feedback else None
        parameter_set = select_parameters(load_json_file(args.input), feedback, {"materials_dir": args.materials_dir})
    except (TuningError, OSError, ValueError) as error:
        sys.stderr.write("error: %s\n" % error)
        return 2
    sys.stdout.write(dumps(parameter_set) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
