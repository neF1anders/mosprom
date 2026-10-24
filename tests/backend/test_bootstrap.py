import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/bootstrap.py").resolve()


def test_the_slicer_folder_is_added_on_a_line_of_its_own(tmp_path):
    """Regression: a .env without a final line break had its last key swallowed."""
    env = tmp_path / ".env"
    env.write_text("SESSION_SECRET=" + "s" * 40)
    subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
    )
    lines = env.read_text().splitlines()
    assert lines == [
        "SESSION_SECRET=" + "s" * 40,
        f"SLICER_HOST_FOLDER={tmp_path / 'Documents' / 'STE_AIAssistant'}",
    ]
