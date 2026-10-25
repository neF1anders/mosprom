import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/bootstrap.py").resolve()


def test_the_slicer_folder_is_added_on_a_line_of_its_own(tmp_path):
    """Папка слайсера на отдельной строке."""
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


def test_a_home_in_cyrillic_reaches_the_env_and_the_plugin_in_utf8(tmp_path):
    """Кириллический путь доходит в UTF-8."""
    home = tmp_path / "Максим"
    home.mkdir()
    env = tmp_path / ".env"
    env.write_text("SESSION_SECRET=" + "s" * 40 + "\n", encoding="utf-8")
    subprocess.run(
        # кодировка ломает скрипт
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            str(SCRIPT),
        ],
        cwd=tmp_path,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
    )
    folder = home / "Documents" / "STE_AIAssistant"
    assert f"SLICER_HOST_FOLDER={folder}" in env.read_text(encoding="utf-8").splitlines()
    config = json.loads((folder / "mosprom.json").read_text(encoding="utf-8"))
    assert (config["origin"], config["user_id"]) == ("http://localhost:8000", "local")
