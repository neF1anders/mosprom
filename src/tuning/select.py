"""select_parameters: task card + geometry -> param_set/0 with a reason for every value."""

import math
import os
from typing import Any  # noqa: F401  (used in type comments)

from tuning.catalog import read_materials
from tuning.contracts import normalize_card, validate_verdict
from tuning.errors import TuningError
from tuning.facts import build_facts
from tuning.hard_rules import fits_build_volume
from tuning.loop import best_record, build_feedback, history_record, key_index, searched_iterations
from tuning.material_choice import choose_material
from tuning.planning import build_plan
from tuning.rules import fired_rules, load_rules, requirement_keys
from tuning.space import Param, load_profile, load_search_space
from tuning.strategies import get_strategy

DEFAULT_CONFIG = {"strategy": "m0", "seed": 1, "max_iterations": 3, "materials_dir": None}
STATE_SCHEMA = "tuning_state/0"


class Preparation(object):
    """Everything derived from the card, geometry and catalog; recomputed on every call (stateless loop).

    Also the read-only description of the search space for experiments: `params` (axes), `plan` (start point
    and allowed interval per parameter), `material`, `profile`.
    """

    def __init__(self, card, geometry, settings):
        self.card, self.warnings = normalize_card(card)
        self.profile, self.space, self.rules = load_profile(), load_search_space(), load_rules()
        materials = read_materials(_materials_dir(settings), self.profile["filament_mm"])
        self.choice, material_warnings = choose_material(self.card, materials)
        self.warnings.extend(material_warnings)
        self.material = self.choice.material
        if self.material.print_temperature is None:
            raise TuningError("material '%s' has no print temperature in the catalog" % self.material.id)
        context = {"profile": self.profile, "material": self.material.context()}
        self.params = {d["id"]: Param(d, context) for d in self.space["params"]}
        facts = build_facts(self.card, geometry)
        self.plan = build_plan(fired_rules(self.rules, facts), self.params, facts, context)
        self.unsatisfied = list(self.choice.unsatisfied)
        self.mode_block, mode_unsatisfied = _choose_mode(self.plan["votes"], geometry, self.profile, self.warnings)
        self.unsatisfied.extend(mode_unsatisfied)
        self.unsatisfied.extend(_plan_unsatisfied(self.plan, self.rules, _requirement_ids_by_key(self.card)))
        self.infeasible = self.choice.infeasible or bool(self.plan["conflicts"]) or bool(mode_unsatisfied)
        self.rule_reasons = {rule["id"]: rule["reason"] for rule in self.rules}
        self.index = key_index(self.space)


def prepare(card, geometry, config=None):
    # type: (dict, dict, Any) -> Preparation
    settings = dict(DEFAULT_CONFIG)
    settings.update(config or {})
    return Preparation(card, geometry, settings)


def render_points(preparation, points):
    # type: (Preparation, dict) -> dict
    """Param_set for explicit t values per parameter (used by the experiment oracle); status is `proposed`."""
    state = {
        "iteration": 0,
        "strategy": "explicit",
        "points": points,
        "vetoed": {},
        "history": [],
        "strategy_state": {},
    }
    return _assemble(preparation, state, "proposed", [])


def select_parameters(card, geometry, state=None, verdict=None, config=None):
    # type: (dict, dict, Any, Any, Any) -> tuple
    """First call: state=None, verdict=None. Next calls: state and verdict of the previous step.

    Returns (param_set, new_state), both JSON-compatible; nothing is kept between calls.
    """
    settings = dict(DEFAULT_CONFIG)
    settings.update(config or {})
    preparation = Preparation(card, geometry, settings)
    if state is None:
        if verdict is not None:
            raise TuningError("a verdict needs the state returned by the previous call")
        return _first_call(preparation, settings)
    if verdict is None:
        raise TuningError("state given without a verdict")
    validate_verdict(verdict)
    return _next_call(preparation, settings, state, verdict)


def _first_call(preparation, settings):
    strategy = get_strategy(settings["strategy"])
    points, strategy_state = strategy.propose(preparation.plan["params"], {}, None, 0)
    state = {
        "schema": STATE_SCHEMA,
        "iteration": 0,
        "strategy": strategy.id,
        "seed": settings["seed"],
        "material": preparation.material.id,
        "mode": preparation.mode_block["value"],
        "points": points,
        "vetoed": {},
        "history": [],
        "strategy_state": strategy_state,
    }
    status = "infeasible" if preparation.infeasible else "proposed"
    return _assemble(preparation, state, status, []), state


def _next_call(preparation, settings, state, verdict):
    if state.get("schema") != STATE_SCHEMA:
        raise TuningError("unknown state schema %r" % state.get("schema"))
    if state["material"] != preparation.material.id or state["mode"] != preparation.mode_block["value"]:
        raise TuningError("state does not match the card: material or mode changed between calls")
    strategy = get_strategy(state["strategy"])
    feedback = build_feedback(verdict, preparation.index)
    new_state = dict(state)
    new_state["history"] = state["history"] + [history_record(state["iteration"], state["points"], verdict)]
    new_state["vetoed"] = dict(state["vetoed"])
    for key, values in feedback["banned"].items():
        new_state["vetoed"][key] = sorted(set(state["vetoed"].get(key, []) + values), key=repr)
    if preparation.infeasible:
        return _assemble(preparation, new_state, "infeasible", []), new_state
    if feedback["ok"]:
        return _assemble(preparation, new_state, "final", []), new_state
    if not strategy.adaptive or state["iteration"] + 1 >= settings["max_iterations"]:
        return _exhausted(preparation, new_state, "exhausted", [])
    points, strategy_state = strategy.propose(
        preparation.plan["params"], state["strategy_state"], feedback, state["iteration"] + 1
    )
    new_state.update({"iteration": state["iteration"] + 1, "points": points, "strategy_state": strategy_state})
    if strategy_state["conflict"]:
        return _exhausted(
            preparation, new_state, "infeasible", _conflict_items(strategy_state["conflict"], verdict, preparation)
        )
    return _assemble(preparation, new_state, "proposed", []), new_state


def _exhausted(preparation, state, status, extra):
    """Budget spent or conflict: hand back the best proposal seen, with the open issues, never as success."""
    best = best_record(state["history"])
    final_state = dict(state)
    final_state["points"] = best["points"]
    final_state["iteration"] = best["iteration"]
    open_issues = [
        {
            "requirement_id": issue["requirement_id"] or issue["id"],
            "why": issue["message"] or "validator issue %s" % issue["id"],
        }
        for issue in best["issues"]
    ]
    return _assemble(preparation, final_state, status, extra + open_issues), state


def _conflict_items(conflict, verdict, preparation):
    related = []
    for issue in verdict.get("issues", []):
        target = preparation.index.get(issue.get("key"))
        if target == ("param", conflict["param"]) and (issue.get("requirement_id") or issue.get("id")) not in related:
            related.append(issue.get("requirement_id") or issue.get("id"))
    item = {"requirement_id": related[0] if related else "param:" + conflict["param"], "why": conflict["why"]}
    if len(related) > 1:
        item["conflicts_with"] = related[1]
    return [item]


def _assemble(preparation, state, status, extra_unsatisfied):
    mode = preparation.mode_block["value"]
    unsatisfied = list(preparation.unsatisfied) + extra_unsatisfied
    return {
        "schema": "param_set/0",
        "iteration": state["iteration"],
        "strategy": state["strategy"],
        "status": status,
        "printing_mode": preparation.mode_block,
        "material": preparation.choice.block,
        "settings": _settings(mode, preparation, state, unsatisfied),
        "orientation": None,
        "assumptions_used": preparation.choice.assumptions,
        "unsatisfied": unsatisfied,
        "warnings": preparation.warnings,
        "build_volume_mm": _build_volume(preparation.profile, mode),
    }


def _materials_dir(settings):
    directory = settings["materials_dir"] or os.environ.get("STE_MATERIALS_DIR")
    if not directory:
        raise TuningError("materials directory is not set: pass --materials-dir or set STE_MATERIALS_DIR")
    if not os.path.isdir(directory):
        raise TuningError("materials directory does not exist: %s" % directory)
    return directory


def _build_volume(profile, mode):
    volume = profile["build_volume_mm"]
    return {"width": volume["width"], "depth": volume["depth"], "height": volume["height"][mode]}


def _choose_mode(votes, geometry, profile, warnings):
    # type: (list, dict, dict, list) -> tuple
    size = geometry["bbox_mm"]["size"]
    valid = [v for v in votes if v["mode"] in profile["modes"]]
    for vote in votes:
        if vote["mode"] not in profile["modes"]:
            warnings.append("printing mode '%s' from rule %s is unknown, ignored" % (vote["mode"], vote["rule_id"]))
    weights = {}  # type: dict
    for vote in valid:
        if fits_build_volume(size, profile, vote["mode"]):
            weights[vote["mode"]] = weights.get(vote["mode"], 0.0) + vote["weight"]
    if not weights:
        fallback = "classic"
        return (
            {
                "value": fallback,
                "source": "default:" + profile["id"],
                "confidence": 0.1,
                "reason": "model does not fit the build volume in any mode as oriented; classic kept as placeholder",
            },
            [
                {
                    "requirement_id": "GEOMETRY",
                    "why": "model size %s mm exceeds the build volume in every mode (orientation not searched)" % size,
                }
            ],
        )
    winner = max(sorted(weights), key=lambda mode: weights[mode])
    top = max((v for v in valid if v["mode"] == winner), key=lambda v: (v["weight"], v["rule_id"]))
    source = "card" if top["rule_id"] == "mode-card-hint" else "rule:" + top["rule_id"]
    return {"value": winner, "source": source, "reason": top["reason"], "confidence": top["confidence"]}, []


def _requirement_ids_by_key(card):
    ids = {}
    for requirement in card.get("requirements", []):
        ids.setdefault(requirement["key"], []).append(requirement["id"])
    return ids


def _plan_unsatisfied(plan, rules, key_ids):
    by_id = {rule["id"]: rule for rule in rules}

    def reference(rule_id):
        found = [i for key in requirement_keys(by_id[rule_id]) for i in key_ids.get(key, [])]
        return found[0] if found else "rule:" + rule_id

    result = []
    for item in plan["unsatisfied"]:
        for requirement_id in key_ids.get(item["requirement_key"], ["rule:" + item["rule_id"]]):
            result.append({"requirement_id": requirement_id, "why": item["why"]})
    for conflict in plan["conflicts"]:
        first, second = (conflict["rules"] + conflict["rules"])[:2]
        result.append(
            {
                "requirement_id": reference(first),
                "conflicts_with": reference(second),
                "why": "rules %s and %s demand incompatible values of %s" % (first, second, conflict["param"]),
            }
        )
    return result


def _explain(entry, rule_reasons, profile_id, searched_at):
    if searched_at is not None:
        reason = "validator feedback moved this value (iteration %d)" % searched_at
        if entry["moving_rule_ids"]:
            reason += "; start point from: " + "; ".join(rule_reasons[r] for r in entry["moving_rule_ids"])
        return "search:it%d" % searched_at, reason
    if entry["moving_rule_ids"]:
        moving = entry["moving_rule_ids"]
        return "rule:" + moving[-1], "; ".join(rule_reasons[rule_id] for rule_id in moving)
    return "default:" + profile_id, "mid-range starting point; no rule moved this parameter"


def _settings(mode, preparation, state, unsatisfied):
    points, vetoed = state["points"], state["vetoed"]
    touched = searched_iterations(state["history"], points, state["iteration"])
    params, plan, space, material, profile = (
        preparation.params,
        preparation.plan,
        preparation.space,
        preparation.material,
        preparation.profile,
    )
    values = {param_id: params[param_id].value_at(points[param_id]) for param_id in params}
    entries = []

    def add(key, value, unit, t, source, rule_ids, reason):
        entries.append(
            {
                "key": key,
                "value": value,
                "unit": unit,
                "target": "global",
                "t": t,
                "source": source,
                "rule_ids": sorted(rule_ids),
                "reason": reason,
            }
        )

    for param_id, param in sorted(params.items()):
        entry = plan["params"][param_id]
        source, reason = _explain(entry, preparation.rule_reasons, profile["id"], touched.get(param_id))
        t = round(points[param_id], 4)
        if param.emit:
            layer = values[param.emit["layer_param"]]
            for key in param.emit["keys"]:
                layers = max(plan["min_layers"].get(key, 0), int(math.ceil(round(values[param_id] / layer, 4))))
                add(
                    key,
                    layers,
                    "",
                    t,
                    source,
                    entry["rule_ids"] + [plan["min_layers_rule"]],
                    "%s; %g mm of solid skin at %g mm layers" % (reason, values[param_id], layer),
                )
            continue
        for key in param.keys[mode]:
            add(key, values[param_id], param.unit, t, source, entry["rule_ids"], reason)

    density = values["infill_density"]
    for definition in space["discrete"]:
        keys = definition["keys"][mode]
        if not keys:
            continue
        chosen = plan["discrete"].get(definition["id"])
        if "from_material" in definition:
            value = getattr(material, definition["from_material"])
            if value is None:
                continue
            source, rule_ids, reason = "default:material:" + material.id, [], "value from the material file"
        elif chosen:
            value, source, rule_ids, reason = (
                chosen["value"],
                "rule:" + chosen["rule_id"],
                [chosen["rule_id"]],
                chosen["reason"],
            )
        else:
            value = definition["default"]
            if definition["id"] == "infill_pattern":
                value = (
                    definition["default_dense"] if density > definition["dense_above_pct"] else definition["default"]
                )
            source, rule_ids, reason = "default:" + profile["id"], [], "profile default; no rule fired"
        banned = vetoed.get(definition["id"], [])
        if value in banned:
            options = [c for c in definition["candidates"] if c not in banned]
            if options:
                value, source, rule_ids = options[0], "search:it%d" % state["iteration"], []
                reason = "previous value rejected by a validator veto; next candidate"
            else:
                unsatisfied.append(
                    {"requirement_id": "discrete:" + definition["id"], "why": "every candidate value was vetoed"}
                )
        for key in keys:
            add(key, value, definition["unit"], None, source, rule_ids, reason)
    return sorted(entries, key=lambda item: item["key"])
