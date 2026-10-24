"""The script that runs cases through the API of a running stand: against its own stand-in of the
API, and the organizer examples it picks up."""

import pytest

from scripts import eval_pipeline

pytestmark = pytest.mark.unit


def test_the_selftest_runs_a_case_through_the_stand_in_api(monkeypatch):
    # The stand-in moves on with every poll, so the pauses between polls only cost time.
    monkeypatch.setattr(eval_pipeline.time, "sleep", lambda seconds: None)
    assert eval_pipeline.selftest() == 0


def test_organizer_folders_with_reference_facts_become_cases(tmp_path):
    """Regression: the reference was looked up in pipeline/tests/eval, so no case was found."""
    folder = tmp_path / "1. Шестерня"
    folder.mkdir()
    (folder / "gear.stl").write_bytes(b"solid gear\nendsolid gear\n")
    (folder / "task.docx").write_bytes(b"docx")
    (tmp_path / "99. Без эталона").mkdir()
    cases = eval_pipeline.load_cases_from_organizer(tmp_path, eval_pipeline.REFERENCE)
    assert [(case[0], [path.name for path in case[2]]) for case in cases] == [
        ("org-1", ["task.docx", "gear.stl"])
    ]


def test_the_stand_address_comes_from_app_origin(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_ORIGIN", raising=False)
    (tmp_path / ".env").write_text("APP_ORIGIN=http://localhost:8000\n", encoding="utf-8")
    assert eval_pipeline._env("APP_ORIGIN") == "http://localhost:8000"
