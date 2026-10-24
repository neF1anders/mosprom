import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from src.backend.domain.catalog import PRINTING_MODES
from src.backend.tuning.axes import SPACE, AxisContext, build_axes, t_interval_for_limits
from src.backend.tuning.constraints import wall_lines
from src.backend.tuning.planning import build_plan, find_conflicts, plan_unmet, resolve_t
from src.backend.tuning.printer import load_printer
from src.backend.tuning.rules import (
    RULE_BY_ID,
    RULES,
    Condition,
    Rule,
    RuleBook,
    holds,
    reason,
    requirement_keys,
    source_of,
)

pytestmark = pytest.mark.unit

CONTEXT = AxisContext(
    nozzle=0.4,
    default_speed=60.0,
    material_temperature=250.0,
    material_speed=50.0,
    speed_floor=25.0,
    temperature_max=285.0,
)
BUILD = Path("knowledge/ste_5.2.4")


def condition(tree):
    return TypeAdapter(Condition).validate_python(tree)


def test_rule_ids_fit_the_source_pattern_of_the_contract():
    assert len({rule.id for rule in RULES}) == len(RULES)
    axes = {spec.id for spec in SPACE.params} | {item.id for item in SPACE.discrete}
    for rule in RULES:
        assert rule.reason and rule.source
        for action in rule.then:
            assert getattr(action, "param", None) in axes | {None}, (rule.id, action)


def test_condition_tree_semantics():
    facts = {"a": 3, "flag": True}
    assert holds(condition({}), facts)
    assert holds(condition({"fact": "a", "op": ">", "value": 2}), facts)
    assert not holds(condition({"fact": "missing", "op": ">", "value": 2}), facts)
    assert holds(condition({"fact": "missing", "op": "exists"}), {"missing": 0})
    assert holds(condition({"not": {"fact": "a", "op": "==", "value": 4}}), facts)
    either = {
        "any": [
            {"fact": "a", "op": "<", "value": 0},
            {"fact": "flag", "op": "==", "value": True},
        ]
    }
    assert holds(condition(either), facts)
    assert not holds(condition({"all": [{"fact": "a", "op": "in", "value": [1, 2]}]}), facts)


def test_axes_are_monotone_from_cheap_to_strong():
    axes = build_axes(CONTEXT)
    layer = axes["layer_height"]
    assert layer.value_at(0.0) == 0.32 and layer.value_at(1.0) == 0.06
    values = [layer.value_at(t / 10.0) for t in range(11)]
    assert values == sorted(values, reverse=True)
    assert axes["print_speed"].value_at(1.0) == 25


def test_value_limits_become_t_intervals_for_both_axis_directions():
    axes = build_axes(CONTEXT)
    low, high = t_interval_for_limits(axes["layer_height"], 0.1, 0.32)
    assert low == pytest.approx(0.0, abs=1e-9) and high == pytest.approx(0.8462, abs=1e-3)
    assert t_interval_for_limits(axes["infill_density"], 30, None) == (0.4, 1.0)


@pytest.mark.parametrize("lines", [2, 3, 4, 5, 6])
def test_sent_wall_thickness_gives_back_the_intended_line_count(catalog, lines):
    width = load_printer(catalog).modes["classic"].line_width
    assert wall_lines(round(lines * width, 4), width) == lines


def test_quality_profile_fast_starts_from_its_own_walls_and_infill(catalog):
    mode = load_printer(catalog).modes["classic"]
    fast = mode.qualities["fast"]
    # 1 mm of wall at 0.4 mm lines: the slicer formula rounds 1.4999... down, so 2 walls.
    assert wall_lines(mode.value("wall_thickness", fast), mode.line_width) == 2
    assert mode.value("infill_sparse_density", fast) == 10


def test_every_key_we_send_exists_in_the_issued_build(catalog):
    keys = {spec.key for spec in SPACE.params}
    for item in SPACE.discrete:
        keys.update(item.constrained_keys())
        assert set(item.mode_keys) <= set(PRINTING_MODES), item.id
    assert keys - set(catalog.settings) == set()


def test_printer_data_comes_from_the_issued_build(catalog):
    printer = load_printer(catalog)
    assert (printer.id, printer.nozzle, printer.filament) == ("hte530v5.2.4", 0.4, 1.75)
    classic, spiral, full = (printer.modes[mode] for mode in PRINTING_MODES)
    assert (classic.width, classic.depth, classic.height) == (351, 300.3, 300)
    assert (classic.elliptic, classic.heated_bed, classic.usable_x) == (
        False,
        True,
        (-169.5, 150.5),
    )
    for five_d in (spiral, full):
        assert (five_d.height, five_d.elliptic, five_d.heated_bed) == (231.1, True, False)
        assert five_d.usable_x == (-175.5, 175.5)
        assert five_d.base_diameter == 6
    assert classic.base_diameter is None
    assert [mode.label for mode in (classic, spiral, full)] == ["3D", "5D Spiral", "5D"]
    assert {mode.temperature_max for mode in (classic, spiral, full)} == {285}
    assert [mode.value("adhesion_type") for mode in (classic, spiral, full)] == [
        "brim",
        "brim",
        "raft",
    ]
    layers = {name: option.layer_height for name, option in classic.qualities.items()}
    assert layers == {
        "high": 0.06,
        "normal": 0.1,
        "fast": 0.15,
        "draft": 0.2,
        "verydraft": 0.3,
        "coarse": 0.4,
        "extra coarse": 0.6,
    }


def test_default_quality_is_the_preferred_one_of_the_build(catalog):
    """The one printer value the catalog does not carry: fdmprinter metadata."""
    definitions = json.loads((BUILD / "definitions/fdmprinter.def.json").read_text())
    preferred = definitions["metadata"]["preferred_quality_type"]
    assert load_printer(catalog).default_quality == preferred


def test_rule_book_refuses_repeated_rule_ids():
    rule = {"id": "R1", "source": "G", "reason": "r", "when": {}, "then": []}
    with pytest.raises(ValidationError):
        RuleBook.model_validate({"note": "", "rules": [rule, rule]})


def test_rules_name_the_requirement_codes_their_conditions_read():
    assert requirement_keys(RULE_BY_ID["INFILL-GYROID"]) == ["flexible"]
    assert requirement_keys(RULE_BY_ID["SUPPORT-OVERHANG"]) == ["no_supports"]
    assert requirement_keys(RULE_BY_ID["TOL-HARD-FINE-LAYER"]) == ["dimensional_tol_mm"]
    assert requirement_keys(RULE_BY_ID["MODE-DEFAULT-CLASSIC"]) == []


def test_reasons_and_sources_of_values():
    assert (reason(None), source_of(None)) == ("значение слайсера", "default")
    assert reason("constraint:C1") == "ограничение этапа 3 (constraint:C1)"
    assert (source_of("constraint:C1"), source_of("STIFF-HARD")) == (
        "constraint:C1",
        "rule:STIFF-HARD",
    )


def test_bound_and_unsatisfied_actions_shape_the_plan():
    rule = Rule.model_validate(
        {
            "id": "SYNTHETIC",
            "source": "G",
            "reason": "r",
            "when": {"fact": "req.no_supports", "op": "==", "value": True},
            "then": [
                {"op": "bound", "param": "print_speed", "min_t": 0.6, "max_t": 0.4},
                {"op": "unsatisfied", "requirement_key": "no_supports", "why": "нависания"},
            ],
        }
    )
    plan = build_plan([rule], build_axes(CONTEXT), CONTEXT)
    entry = plan.axes["print_speed"]
    assert (entry.low, entry.high, entry.low_rule, entry.high_rule) == (
        0.6,
        0.4,
        "SYNTHETIC",
        "SYNTHETIC",
    )
    assert resolve_t(entry, 0.0) == (0.5, "SYNTHETIC")
    conflicts = find_conflicts(plan)
    unmet = plan_unmet(plan, conflicts, {"no_supports": ["no_supports"]}, {"SYNTHETIC": rule})
    assert [(item.requirement_id, item.conflicts_with) for item in unmet] == [
        ("no_supports", None),
        ("no_supports", None),
    ]
    assert unmet[0].why == "нависания"
    without_card = plan_unmet(plan, [], {}, {"SYNTHETIC": rule})
    assert [item.requirement_id for item in without_card] == ["rule:SYNTHETIC"]
