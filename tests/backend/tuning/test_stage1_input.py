import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.models import TaskCard
from src.backend.domain.requirement_keys import RequirementKey
from src.backend.tuning.facts import build_facts
from src.backend.tuning.intake import Unreadable, read_card, read_flag, stricter_end
from src.backend.tuning.materials import printable_materials
from src.backend.tuning.select import READ_CODES, select_parameters
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
    material = select(card(requirements=[requirement("material", "PLA")]))["materials"]["0"]
    assert material["id"] == "generic_pla_175"
    assert material["source"] == "requirement:material"


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


def test_unconfirmed_load_is_told_but_moves_no_setting(select):
    # An assumed load added walls and gyroid infill to parts nobody said were loaded.
    guessed = card(
        requirements=[
            requirement("load_bearing", "cyclic", provenance="assumption", verified=False),
            requirement("printing_mode", "classic", provenance="assumption", verified=False),
        ]
    )
    parameter_set = select(guessed)
    assert parameter_set["settings"]["wall_thickness"]["source"] == "rule:WALLS-STANDARD"
    assert "infill_pattern" not in parameter_set["settings"]
    texts = assumption_texts(parameter_set)
    assert (
        "нагрузка «cyclic» в карточке не подтверждена: подбор её не учитывает, подтвердите её, "
        "если деталь нагружена"
    ) in texts
    assert "режим печати classic в карточке не подтверждён и принят как допущение" in texts


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


def test_wish_phrases_match_only_at_the_start_of_a_word(select):
    # "точн" was found in "достаточно" and "допуск" in "допускаются": priority accuracy.
    wishes = card(preferences=["деталь должна быть достаточно прочной, допускаются поддержки"])
    texts = assumption_texts(select(wishes))
    assert "приоритеты strength выведены из текста пожеланий" in texts
    assert not any("accuracy" in text for text in texts)
    tolerance = card(preferences=["Главное допуски на посадку, потом прочность"])
    assert "приоритеты accuracy, strength выведены из текста пожеланий" in assumption_texts(
        select(tolerance)
    )


def test_material_without_print_temperature_is_skipped_or_refused(catalog, keys):
    files = dict(catalog.materials)
    files["generic_pla_175"] = replace(files["generic_pla_175"], print_temperature=None)
    broken = replace(catalog, materials=files)
    parameter_set = select_parameters(card(), broken, keys).published()
    assert parameter_set["materials"]["0"]["id"] != "generic_pla_175"
    assert (
        "material generic_pla_175 has no print temperature in the catalog, skipped"
        in parameter_set["warnings"]
    )
    named = card(requirements=[requirement("material", "generic_pla_175")])
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
    extended = keys.model_copy(update={"keys": [*keys.keys, finish]})
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


def test_overhangs_of_the_report_switch_supports_on(select):
    parameter_set = select(card(stl_report=report(overhang_fraction=0.2)))
    support = parameter_set["settings"]["support_enable"]
    assert support["value"] is True and support["source"] == "rule:SUPPORT-OVERHANG"
    texts = assumption_texts(parameter_set)
    assert not any(text.startswith("доли нависаний нет") for text in texts)
    assert (
        "ориентация «как загружено» и положение в центре рабочей области стола, поворот в 3D "
        "не подбирается"
    ) in texts


def test_overhang_share_reaches_the_rules_as_a_fact(catalog, keys):
    material = next(iter(printable_materials(catalog, 1.75).candidates.values()))
    measured = read_card(card(stl_report=report(overhang_fraction=0.03)), keys, READ_CODES)
    assert build_facts(measured, material)["geometry.overhang_area_fraction"] == 0.03
    assert "geometry.overhang_area_fraction" not in build_facts(
        read_card(card(), keys, READ_CODES), material
    )


def test_overhangs_with_supports_forbidden_are_unmet_and_stay_in_3d(select):
    # Not a body of revolution (a figurine): 5D Spiral would not help it.
    forbidden = card(
        stl_report=report(overhang_fraction=0.2), requirements=[requirement("no_supports", "да")]
    )
    parameter_set = select(forbidden)
    assert "support_enable" not in parameter_set["settings"]
    assert [item["requirement_id"] for item in parameter_set["unsatisfied"]] == ["no_supports"]
    assert parameter_set["printing_mode"]["value"] == "classic"


def test_overhangs_of_a_body_of_revolution_with_supports_forbidden_vote_for_5d_spiral(select):
    forbidden = card(
        stl_report=report(overhang_fraction=0.2, bore=8.0),
        requirements=[requirement("no_supports", "да")],
    )
    parameter_set = select(forbidden)
    assert parameter_set["printing_mode"]["source"] == "rule:MODE-OVERHANG-5D"


def test_supports_allowed_by_a_mandatory_no_supports_are_used_on_overhangs(select):
    # The rules read only that no_supports is mandatory, not that its value is "no".
    allowed = card(
        stl_report=report(overhang_fraction=0.3), requirements=[requirement("no_supports", "нет")]
    )
    parameter_set = select(allowed)
    assert parameter_set["settings"]["support_enable"]["source"] == "rule:SUPPORT-OVERHANG"
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert parameter_set["unsatisfied"] == []


def test_wish_to_print_without_supports_is_reported_when_overhangs_need_them(select):
    wish = card(
        stl_report=report(overhang_fraction=0.3),
        requirements=[requirement("no_supports", "да", mandatory=False)],
    )
    parameter_set = select(wish)
    assert parameter_set["settings"]["support_enable"]["value"] is True
    assert parameter_set["printing_mode"]["value"] == "classic"
    assert parameter_set["unsatisfied"] == [
        {
            "requirement_id": "no_supports",
            "why": "у модели есть нависания, поэтому поддержки включены вопреки пожеланию "
            "печатать без них",
        }
    ]


def test_priority_code_comes_before_the_wishes(keys, select):
    coded = card(
        requirements=[requirement("priority", "Speed, quality; strength, speed")],
        preferences=["Важна прочность, затем точность"],
    )
    request = read_card(coded, keys, READ_CODES)
    assert request.priority == ("speed", "strength")
    assert "priority" not in {requirement.key for requirement in request.requirements}
    assert not any("выведены из текста" in text for text in request.assumptions)
    assert (
        "priority priority (priority): quality not one of strength, accuracy, speed, cost"
        in request.warnings
    )
    assert select(coded)["settings"]["layer_height"]["source"] == "rule:PRIORITY-SPEED-LAYER"


def test_unconfirmed_priority_code_is_told_as_an_assumption(keys):
    unconfirmed = card(requirements=[requirement("priority", "cost", verified=False)])
    request = read_card(unconfirmed, keys, READ_CODES)
    assert request.priority == ("cost",)
    assert (
        "приоритеты cost в карточке не подтверждены и приняты как допущение" in request.assumptions
    )


def test_priority_code_without_a_known_value_leaves_the_wishes(keys):
    stated = card(
        requirements=[requirement("priority", "качество")],
        preferences=["Важна прочность, затем точность"],
    )
    request = read_card(stated, keys, READ_CODES)
    assert request.priority == ("strength", "accuracy")
    assert (
        "обязательное требование priority (priority): expected some of strength, accuracy, "
        "speed, cost, got 'качество' не учтено подбором параметров"
    ) in request.assumptions
    assert "приоритеты strength, accuracy выведены из текста пожеланий" in request.assumptions


def test_codes_no_step_reads_are_told_as_not_taken_into_account(select):
    # A mandatory code no rule or material check reads was accepted and dropped silently.
    parameter_set = select(
        card(
            requirements=[
                requirement("rotation_speed_max_rpm", "450", "об/мин"),
                requirement("sealed", "да", mandatory=False),
            ]
        )
    )
    assert (
        "обязательное требование rotation_speed_max_rpm (rotation_speed_max_rpm) не учтено "
        "подбором параметров"
    ) in assumption_texts(parameter_set)
    assert (
        "requirement sealed (sealed) is not used by parameter selection"
        in (parameter_set["warnings"])
    )


def test_part_class_is_read_by_the_mode_rules(select):
    parameter_set = select(card(requirements=[requirement("part_class", "gear")]))
    assert not any("part_class" in text for text in assumption_texts(parameter_set))
    assert not any("part_class" in text for text in parameter_set["warnings"])
    assert parameter_set["printing_mode"]["value"] == "classic"


def test_material_properties_without_catalog_data_are_told_as_unchecked(select):
    # A short peak temperature has no data: "proposed" with a word about it. The modulus and the
    # heat deflection are checked against the typical values of the traits table.
    parameter_set = select(
        card(
            requirements=[
                requirement("service_temp_peak_c", "160", "°C"),
                requirement("tensile_modulus_min_mpa", "2500", "МПа"),
                requirement("heat_deflection_min_c", "120", "°C"),
            ]
        )
    )
    texts = assumption_texts(parameter_set)
    assert (
        "требование service_temp_peak_c не проверено по каталогу: "
        "cannot be checked from the catalog" in texts
    )
    checks = {check["key"]: check for check in parameter_set["materials"]["0"]["checks"]}
    assert checks["service_temp_peak_c"]["status"] == "unknown"
    assert checks["tensile_modulus_min_mpa"]["detail"].startswith("modulus_mpa=")
    assert checks["heat_deflection_min_c"]["detail"].startswith("hdt_c=")


def test_high_friction_is_checked_against_the_friction_of_the_material(select):
    checks = select(card(requirements=[requirement("high_friction", "да")]))["materials"]["0"][
        "checks"
    ]
    (check,) = checks
    assert (check["key"], check["status"]) == ("high_friction", "ok")


def test_percent_codes_are_read_in_percent(keys):
    stated = card(
        requirements=[
            requirement("water_absorption_max_pct", "0,05–0,1", "%"),
            requirement("elongation_min_pct", "20", "%"),
        ]
    )
    read = [(found.key, found.value) for found in read_card(stated, keys, READ_CODES).requirements]
    assert read == [("water_absorption_max_pct", 0.05), ("elongation_min_pct", 20.0)]


def test_contract_example_is_selected_with_overhangs_and_priority(select):
    schema = json.loads(Path("docs/stage1-contract.schema.json").read_text(encoding="utf-8"))
    example = {key: value for key, value in schema["examples"][0].items() if key != "_comment"}
    parameter_set = select(TaskCard.model_validate(example))
    settings = parameter_set["settings"]
    assert parameter_set["status"] == "proposed"
    # Supports follow the overhangs of the upright pose, not of the file as loaded.
    (model,) = parameter_set["models"]
    assert model["orientation_candidate"] != "o1"
    assert "support_enable" not in settings
    assert any(setting["source"] == "rule:PRIORITY-STRENGTH" for setting in settings.values())
    not_used = [text for text in assumption_texts(parameter_set) if "не учтено" in text]
    # The wheel of the example is printed in 5D with its axis upright.
    assert parameter_set["printing_mode"]["source"] == "rule:MODE-REVOLUTION-5D"
    assert parameter_set["printing_mode"]["value"] == "cylindrical_full"
    assert not_used == [
        "обязательное требование rotation_speed_max_rpm (Частота вращения) не учтено подбором "
        "параметров",
    ]
    # «Без микропыли» is read from its words as abrasion resistance and told as an assumption.
    assert any(
        "«Без микропыли» понято как abrasion_resistant" in text
        for text in assumption_texts(parameter_set)
    )


def test_choice_code_is_read_only_from_its_options(keys):
    coded = card(
        requirements=[
            requirement("print_quality", "Fine"),
            requirement("print_quality", "ultra", mandatory=False),
        ]
    )
    request = read_card(coded, keys, READ_CODES)
    assert [(item.key, item.value) for item in request.requirements] == [("print_quality", "fine")]
    assert any("print_quality-2" in text and "ultra" in text for text in request.warnings)
