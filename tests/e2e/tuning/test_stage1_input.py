import json

import pytest
from loop_helpers import issue
from stage1_factory import handoff, report, requirement, write_handoff

from tuning.contracts import param_set_errors
from tuning.errors import TuningError
from tuning.intake.values import parse_bool, parse_number, parse_numbers

GEAR = dict(
    requirements=[
        requirement("tg_min_c", "85–90", "°C"),
        requirement("high_stiffness", "да"),
        requirement("load_bearing", "Циклическая нагрузка"),
        requirement("airtightness", "Без требований"),
        requirement("dimensional_tol_mm", "0.15", "мм", mandatory=False, provenance="assumption", verified=False),
    ],
    preferences=["Важна прочность, затем точность"],
)


def select(run_tuning, tmp_path, payload, *extra):
    code, out, err = run_tuning("select", "--input", write_handoff(tmp_path / "handoff.json", payload), *extra)
    return code, (json.loads(out) if code == 0 else None), err


def test_handoff_gives_explained_parameters_tied_to_the_revision(run_tuning, tmp_path):
    code, param_set, err = select(run_tuning, tmp_path, handoff(**GEAR))
    assert code == 0, err
    assert param_set_errors(param_set) == []
    assert param_set["status"] == "proposed" and param_set["idempotency_key"] == "job-1:1"
    keys = {setting["key"]: setting for setting in param_set["settings"]}
    assert keys["wall_line_count"]["source"] == "rule:stiffness-hard"
    assumptions = param_set["assumptions_used"]
    assert "STL units are unknown: coordinates are taken as millimetres" in assumptions
    assert "mandatory requirement airtightness (airtightness) is not used by parameter selection" in assumptions
    assert "priority strength, accuracy read from the preference text" in assumptions
    assert any(a.startswith("dimensional_tol_mm dimensional_tol_mm=0.15 is an assumption") for a in assumptions)


def test_unknown_overhangs_leave_supports_off_and_say_so(run_tuning, tmp_path):
    code, param_set, err = select(run_tuning, tmp_path, handoff())
    assert code == 0, err
    supports = [s for s in param_set["settings"] if s["key"] == "support_enable_classic"]
    assert supports[0]["value"] is False
    assert any(a.startswith("overhang area is not in the stage-1 report") for a in param_set["assumptions_used"])


def test_confirmed_millimetres_are_not_an_assumption(run_tuning, tmp_path):
    payload = handoff(stl_report=report(coordinate_unit="mm"))
    code, param_set, err = select(run_tuning, tmp_path, payload)
    assert code == 0, err
    assert "model coordinates are millimetres (confirmed by stage 1)" in param_set["assumptions_used"]


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"readiness": "blocked", "blocked_actions": {"select_parameters": ["no material"]}}, "no material"),
        ({"readiness": "ready", "blocked_actions": {"select_parameters": ["units"]}}, "units"),
        ({"schema_version": "1.0"}, "schema_version"),
    ],
)
def test_card_not_released_for_selection_is_refused(run_tuning, tmp_path, fields, message):
    code, _, err = select(run_tuning, tmp_path, handoff(**fields))
    assert code == 2 and message in err


def test_preliminary_card_is_used_with_a_caveat(run_tuning, tmp_path):
    code, param_set, err = select(run_tuning, tmp_path, handoff(readiness="preliminary"))
    assert code == 0, err
    assert param_set["assumptions_used"][0].startswith("task card is preliminary")


def test_report_of_another_stl_is_refused(run_tuning, tmp_path):
    payload = handoff()
    payload["card"]["stl_analysis"]["sha256"] = "f" * 64
    code, _, err = select(run_tuning, tmp_path, payload)
    assert code == 2 and "sha256" in err


def test_card_without_report_is_refused(run_tuning, tmp_path):
    payload = handoff()
    payload["card"]["stl_analysis"] = None
    code, _, err = select(run_tuning, tmp_path, payload)
    assert code == 2 and "stl_analysis" in err


def test_loop_state_of_another_revision_is_refused(run_tuning, tmp_path):
    state_path, verdict_path = tmp_path / "state.json", tmp_path / "verdict.json"
    code, _, err = select(run_tuning, tmp_path, handoff(), "--strategy", "m1", "--state-out", str(state_path))
    assert code == 0, err
    verdict_path.write_text(json.dumps({"ok": False, "issues": [issue("infill_sparse_density", "too_weak")]}))
    loop = ("--strategy", "m1", "--state", str(state_path), "--verdict", str(verdict_path))
    code, second, err = select(run_tuning, tmp_path, handoff(), *loop)
    assert code == 0 and second["iteration"] == 1, err
    code, _, err = select(run_tuning, tmp_path, handoff(key="job-1:2"), *loop)
    assert code == 2 and "job-1:2" in err


def test_same_handoff_gives_identical_bytes(run_tuning, tmp_path):
    first = select(run_tuning, tmp_path, handoff(**GEAR))
    second = select(run_tuning, tmp_path, handoff(**GEAR))
    assert first[0] == 0 and first[1] == second[1]


def test_cli_requires_exactly_one_input_form(run_tuning, tmp_path, block_stl):
    path = write_handoff(tmp_path / "handoff.json", handoff())
    code, _, err = run_tuning("select", "--input", path, "--stl", block_stl)
    assert code == 2 and "either --input" in err


@pytest.mark.parametrize(
    "text, stricter, expected",
    [("85", "upper", 85.0), ("85–90", "upper", 90.0), ("85-90", "lower", 85.0), ("0,15", "lower", 0.15)],
)
def test_requirement_numbers_take_the_stricter_end_of_a_range(text, stricter, expected):
    assert parse_number(text, stricter) == expected


def test_minus_is_a_sign_only_at_a_word_start():
    assert parse_numbers("-10..70") == [-10.0, 70.0]
    assert parse_numbers("10-70") == [10.0, 70.0]


def test_ambiguous_values_are_rejected():
    with pytest.raises(TuningError):
        parse_number("1, 2 или 3", "upper")
    with pytest.raises(TuningError):
        parse_bool("скорее да", {"true": ["да"], "false": ["нет"]})
