import json
import subprocess
import sys
from pathlib import Path

import trimesh

SCRIPT = Path(__file__).resolve().parents[2] / "src" / "mesh_analysis.py"


def test_cli_batch_and_error_report(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    trimesh.creation.box(extents=[2, 3, 4]).export(inputs / "куб.STL")
    (inputs / "broken.stl").write_bytes(b"broken")
    output = tmp_path / "reports"
    run = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(inputs),
            "--output-dir",
            str(output),
            "--samples",
            "0",
            "--units",
            "mm",
            "--preview",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 1, run.stderr
    index = json.loads((output / "index.json").read_text())
    assert len(index) == 2
    assert {r["status"] for r in index} == {"checks_passed", "error"}
    good = next(r for r in index if r["status"] == "checks_passed")
    report = json.loads((output / good["json"]).read_text())
    assert report["geometry"]["volume"] == 24
    assert (output / good["markdown"]).exists()
    assert list(output.glob("*.png"))
