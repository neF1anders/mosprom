from dataclasses import replace
from decimal import Decimal

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.requirement_keys import RequirementKey, RequirementKeys
from src.backend.tuning.intake import Unreadable, read_flag, stricter_end
from src.backend.tuning.select import select_parameters
from tests.backend.tuning.cards import SHA, card, report, requirement

pytestmark = pytest.mark.unit


def assumption_texts(parameter_set):
    return [entry["text"] for entry in parameter_set["assumptions"]]


def test_card_ref_comes_from_the_job_and_revision_of_the_card(select):
    parameter_set = select(card(job_id="job-7", revision=4))
    assert parameter_set["card_ref"] == {"job_id": "job-7", "revision": 4}
    assert "idempotency_key" not in parameter_set


def test_input_assumptions_reach_the_user(select):
    stated = card(
        requirements=[
            requirement("airtightness", "Без требований"),
            requirement(
                "dimensional_tol_mm",
                "0.15",
                "мм",
                mandatory=False,
                provenance="assumption",
                verified=False,
            ),
        ],
        preferences=["Важна прочность, затем точность"],
        assumptions=["одна модель на партию"],
    )
    texts = assumption_texts(select(stated))
    assert "единицы STL неизвестны: координаты приняты за миллиметры" in texts
    assert (
        "обязательное требование airtightness (airtightness) не учтено подбором параметров" in texts
    )
    assert "приоритеты strength, accuracy выведены из текста пожеланий" in texts
    assert "одна модель на партию" in texts
    assert "требование dimensional_tol_mm = 0.15 — допущение, а не подтверждённый факт" in texts


def test_unknown_overhangs_leave_supports_off_and_say_so(select):
    parameter_set = select(card())
    assert "support_enable" not in parameter_set["settings"]
    assert (
        "доли нависаний нет в отчёте STL этапа 1: поддержки по геометрии не включаются"
        in assumption_texts(parameter_set)
    )


def test_confirmed_millimetres_are_not_an_assumption(select):
    parameter_set = select(card(stl_report=report(coordinate_unit="mm")))
    assert "координаты модели в миллиметрах (подтверждено этапом 1)" in assumption_texts(
        parameter_set
    )


@pytest.mark.parametrize(
    ("fields", "code", "message"),
    [
        (
            {"readiness": "blocked", "blocked_actions": {"select_parameters": ["no material"]}},
            "card_blocked",
            "no material",
        ),
        (
            {"readiness": "ready", "blocked_actions": {"select_parameters": ["units"]}},
            "card_blocked",
            "units",
        ),
        ({"readiness": "blocked"}, "card_blocked", "Этап 1"),
        ({"schema_version": "1.1"}, "card_schema", "1.1"),
    ],
)
def test_card_not_released_for_selection_is_refused(select, fields, code, message):
    with pytest.raises(AppError) as refused:
        select(card(**fields))
    assert refused.value.code == code and message in refused.value.message


def test_preliminary_card_is_used_with_a_caveat(select):
    parameter_set = select(card(readiness="preliminary"))
    assert parameter_set["assumptions"][0]["text"].startswith("карточка предварительная")


def test_report_of_another_stl_is_refused(select):
    other = card()
    other.stl_analysis.sha256 = "f" * 64
    with pytest.raises(AppError) as refused:
        select(other)
    assert refused.value.code == "stl_report_mismatch"


@pytest.mark.parametrize(
    ("analysis", "code"),
    [
        (None, "stl_report_missing"),
        ({"attachment_id": "att-1", "sha256": SHA, "report": {}}, "stl_report_missing"),
        (
            {"attachment_id": "att-1", "sha256": SHA, "report": {"geometry": {}}},
            "stl_report_bounds",
        ),
        (
            {"attachment_id": "att-1", "sha256": SHA, "report": report(coordinate_unit="inch")},
            "stl_report_units",
        ),
        (
            {"attachment_id": "att-1", "sha256": SHA, "report": {"geometry": {"bounds": "box"}}},
            "stl_report_invalid",
        ),
    ],
)
def test_card_without_a_usable_report_is_refused(select, analysis, code):
    with pytest.raises(AppError) as refused:
        select(card(stl_analysis=analysis))
    assert refused.value.code == code


def test_partial_errors_of_the_analyzer_are_warnings(select):
    broken = report()
    broken["partial_errors"] = {"sections": "ValueError"}
    warnings = select(card(stl_report=broken))["warnings"]
    assert "stl report partial error: sections (ValueError)" in warnings


def test_material_named_by_the_user_matches_the_extruder_filament(select):
    material = select(card(answers={"material_choice": "PLA"}))["materials"]["0"]
    assert material["id"] == "generic_pla_175"
    assert material["source"] == "requirement:answer.material_choice"


def test_unconfirmed_material_is_not_used(select):
    guessed = card(requirements=[requirement("material", "Enduse PC", verified=False)])
    parameter_set = select(guessed)
    assert parameter_set["materials"]["0"]["source"] == "rule:MATERIAL-RANK"
    assert (
        "material material (material) is not confirmed, catalog ranking is used"
        in parameter_set["warnings"]
    )


def test_chemical_media_in_russian_are_matched_to_the_catalog_text(select):
    resistant = card(requirements=[requirement("chemical_resistance", "щёлочи, масла")])
    material = select(resistant)["materials"]["0"]
    assert material["id"] == "enduse_pa6"
    assert [check["status"] for check in material["checks"]] == ["ok"]


def test_repeated_requirement_codes_get_ids_the_validator_accepts(select):
    repeated = card(
        requirements=[requirement("tg_min_c", "60", "°C"), requirement("tg_min_c", "90", "°C")]
    )
    ids = [check["requirement_id"] for check in select(repeated)["materials"]["0"]["checks"]]
    assert ids == ["tg_min_c", "tg_min_c-2"]


def test_numbers_in_another_unit_of_the_same_kind_are_converted(select):
    in_centimetres = select(card(requirements=[requirement("dimensional_tol_mm", "0.01", "см")]))
    assert in_centimetres["settings"]["speed_print"]["source"] == "rule:TOL-HARD-FINE-LAYER"
    in_kelvin = select(card(requirements=[requirement("tg_min_c", "358.15", "K")]))
    (check,) = in_kelvin["materials"]["0"]["checks"]
    assert check["status"] == "ok"


def test_numbers_in_a_unit_of_another_kind_are_not_used(select):
    texts = assumption_texts(select(card(requirements=[requirement("tg_min_c", "85", "мм")])))
    assert (
        "обязательное требование tg_min_c (tg_min_c): unit 'мм', expected °C "
        "не учтено подбором параметров"
    ) in texts


def test_canonical_load_code_is_taken_as_stated(select):
    parameter_set = select(card(requirements=[requirement("load_bearing", "cyclic")]))
    assert parameter_set["settings"]["wall_thickness"]["source"] == "rule:LOAD-WALLS"
    assert not any(text.startswith("нагрузка") for text in assumption_texts(parameter_set))


def test_load_is_read_from_production_constraints(select):
    parameter_set = select(card(production_constraints=["Работа при вибрации привода"]))
    assert parameter_set["settings"]["infill_pattern"]["value"] == "gyroid"
    assert (
        "нагрузка «cyclic» выведена из текста: ограничение производства «Работа при вибрации "
        "привода»"
    ) in assumption_texts(parameter_set)


def test_supports_forbidden_by_the_wishes_are_an_assumption(select):
    texts = assumption_texts(select(card(preferences=["Печатать без поддержек"])))
    assert "поддержки запрещены по тексту пожеланий" in texts


def test_material_without_print_temperature_is_skipped_or_refused(catalog, keys):
    files = dict(catalog.materials)
    files["enduse_abs"] = replace(files["enduse_abs"], print_temperature=None)
    broken = replace(catalog, materials=files)
    parameter_set = select_parameters(card(), broken, keys).published()
    assert parameter_set["materials"]["0"]["id"] != "enduse_abs"
    assert (
        "material enduse_abs has no print temperature in the catalog, skipped"
        in parameter_set["warnings"]
    )
    named = card(requirements=[requirement("material", "Enduse ABS")])
    with pytest.raises(AppError) as refused:
        select_parameters(named, broken, keys)
    assert refused.value.code == "material_without_temperature"


@pytest.mark.parametrize(
    ("text", "strict", "expected"),
    [
        ("85", "upper", "85"),
        ("85–90", "upper", "90"),
        ("85-90", "lower", "85"),
        ("0,15", "lower", "0.15"),
        ("-10..70", "upper", "70"),
        ("от +10 до +70", "upper", "70"),
    ],
)
def test_requirement_numbers_take_the_stricter_end_of_a_range(text, strict, expected):
    assert stricter_end(text, strict) == Decimal(expected)


def test_ambiguous_values_are_rejected():
    with pytest.raises(Unreadable):
        stricter_end("1, 2 или 3", "upper")
    with pytest.raises(Unreadable):
        read_flag("скорее да")
    assert read_flag(" Да ") is True and read_flag("не требуется") is False


def test_unreadable_values_are_told_and_not_used(select):
    unreadable = card(
        requirements=[
            requirement("quantity", "много"),
            requirement("chemical_resistance", " ; "),
            requirement("load_bearing", "переменная"),
            requirement("hydrophobic", "скорее да", mandatory=False),
        ]
    )
    parameter_set = select(unreadable)
    warnings, texts = parameter_set["warnings"], assumption_texts(parameter_set)
    assert "quantity quantity (quantity): expected a number or a range, got 'много'" in warnings
    assert (
        "обязательное требование chemical_resistance (chemical_resistance): expected a list, "
        "got ' ; ' не учтено подбором параметров"
    ) in texts
    assert "load of load_bearing (load_bearing) not recognised: 'переменная'" in warnings
    assert (
        "requirement hydrophobic (hydrophobic): expected yes/no, got 'скорее да' is not used "
        "by parameter selection"
    ) in warnings


def test_code_of_a_kind_selection_does_not_read_is_not_taken_into_account(catalog, keys):
    finish = RequirementKey(key="surface_finish", kind="text", title="Чистота поверхности")
    extended = RequirementKeys(keys=[*keys.keys, finish])
    stated = card(requirements=[requirement("surface_finish", "Ra 3.2")])
    parameter_set = select_parameters(stated, catalog, extended).published()
    assert (
        "обязательное требование surface_finish (surface_finish) не учтено подбором параметров"
        in assumption_texts(parameter_set)
    )


def test_number_codes_of_the_shared_dictionary_have_units(keys):
    card_fields = {"quantity", "load_bearing", "printing_mode", "material"}
    for entry in keys.keys:
        if entry.kind == "number" and entry.key not in card_fields:
            assert entry.unit, entry.key
