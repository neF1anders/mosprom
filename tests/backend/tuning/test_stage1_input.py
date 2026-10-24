import pytest
from stage1_factory import handoff, report, requirement

from tuning.errors import TuningError
from tuning.intake.values import parse_bool, parse_number, parse_numbers


def assumption_texts(parameter_set):
    return [entry["text"] for entry in parameter_set["assumptions"]]


def test_card_ref_comes_from_the_idempotency_key_and_revision(select):
    code, parameter_set, err = select(handoff(key="job-7:4", revision=4))
    assert code == 0, err
    assert parameter_set["card_ref"] == {"job_id": "job-7", "revision": 4}
    assert parameter_set["idempotency_key"] == "job-7:4"


def test_bare_card_takes_the_job_from_source_versions(select):
    payload = handoff(source_versions=[{"id": "att-1", "sha256": "0" * 64}, {"id": "job-9", "revision": "1"}])
    code, parameter_set, err = select(payload["card"])
    assert code == 0, err
    assert parameter_set["card_ref"] == {"job_id": "job-9", "revision": 1}


def test_input_assumptions_reach_the_user(select):
    payload = handoff(
        requirements=[
            requirement("airtightness", "Без требований"),
            requirement("dimensional_tol_mm", "0.15", "мм", mandatory=False, provenance="assumption", verified=False),
        ],
        preferences=["Важна прочность, затем точность"],
        assumptions=["одна модель на партию"],
    )
    code, parameter_set, err = select(payload)
    assert code == 0, err
    texts = assumption_texts(parameter_set)
    assert "единицы STL неизвестны: координаты приняты за миллиметры" in texts
    assert "обязательное требование airtightness (airtightness) не учтено подбором параметров" in texts
    assert "приоритеты strength, accuracy выведены из текста пожеланий" in texts
    assert "одна модель на партию" in texts
    assert "требование dimensional_tol_mm = 0.15 — допущение, а не подтверждённый факт" in texts


def test_unknown_overhangs_leave_supports_off_and_say_so(select):
    code, parameter_set, err = select(handoff())
    assert code == 0, err
    assert "support_enable" not in parameter_set["settings"]
    assert "доли нависаний нет в отчёте STL этапа 1: поддержки по геометрии не включаются" in assumption_texts(
        parameter_set
    )


def test_confirmed_millimetres_are_not_an_assumption(select):
    code, parameter_set, err = select(handoff(stl_report=report(coordinate_unit="mm")))
    assert code == 0, err
    assert "координаты модели в миллиметрах (подтверждено этапом 1)" in assumption_texts(parameter_set)


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"readiness": "blocked", "blocked_actions": {"select_parameters": ["no material"]}}, "no material"),
        ({"readiness": "ready", "blocked_actions": {"select_parameters": ["units"]}}, "units"),
        ({"schema_version": "1.0"}, "schema_version"),
    ],
)
def test_card_not_released_for_selection_is_refused(select, fields, message):
    code, _, err = select(handoff(**fields))
    assert code == 2 and message in err


def test_preliminary_card_is_used_with_a_caveat(select):
    code, parameter_set, err = select(handoff(readiness="preliminary"))
    assert code == 0, err
    assert parameter_set["assumptions"][0]["text"].startswith("карточка предварительная")


def test_report_of_another_stl_is_refused(select):
    payload = handoff()
    payload["card"]["stl_analysis"]["sha256"] = "f" * 64
    code, _, err = select(payload)
    assert code == 2 and "sha256" in err


def test_card_without_report_is_refused(select):
    payload = handoff()
    payload["card"]["stl_analysis"] = None
    code, _, err = select(payload)
    assert code == 2 and "stl_analysis" in err


def test_material_named_by_the_user_matches_the_extruder_filament(select):
    code, parameter_set, err = select(handoff(answers={"material_choice": "PLA"}))
    assert code == 0, err
    material = parameter_set["materials"]["0"]
    assert material["id"] == "generic_pla_175" and material["source"] == "requirement:answer.material_choice"


def test_chemical_media_in_russian_are_matched_to_the_catalog_text(select):
    code, parameter_set, err = select(handoff(requirements=[requirement("chemical_resistance", "щёлочи, масла")]))
    assert code == 0, err
    material = parameter_set["materials"]["0"]
    assert material["id"] == "enduse_pa6"
    assert [check["status"] for check in material["checks"]] == ["ok"]


def test_repeated_requirement_codes_get_ids_the_validator_accepts(select):
    payload = handoff(requirements=[requirement("tg_min_c", "60", "°C"), requirement("tg_min_c", "90", "°C")])
    code, parameter_set, err = select(payload)
    assert code == 0, err
    ids = [check["requirement_id"] for check in parameter_set["materials"]["0"]["checks"]]
    assert ids == ["tg_min_c", "tg_min_c-2"]


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
