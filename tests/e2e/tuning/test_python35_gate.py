import ast
import glob
import os

import pytest

SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src", "tuning")
FILES = sorted(glob.glob(os.path.join(SOURCE, "**", "*.py"), recursive=True))


def parse_as_python35(source):
    return ast.parse(source, feature_version=(3, 5))


@pytest.mark.parametrize("path", FILES)
def test_module_is_valid_python35_syntax(path):
    with open(path, encoding="utf-8") as stream:
        parse_as_python35(stream.read())


def test_gate_covers_every_module():
    assert len(FILES) > 10


@pytest.mark.parametrize("snippet", ['name = "x"\nf"{name}"\n', "value: int = 1\n", "if (n := 3):\n    pass\n"])
def test_gate_rejects_syntax_newer_than_python35(snippet):
    with pytest.raises(SyntaxError):
        parse_as_python35(snippet)
