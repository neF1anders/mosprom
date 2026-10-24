"""Stage-2 decisions: material, printing mode, quality profile, settings that differ from the slicer, model placement.

Every searched axis starts at the value the slicer would use anyway (quality profile, material file, definition)
and moves only when a rule or a validator constraint asks for it; only such differences become `settings`.
"""

import math
from typing import Any  # noqa: F401  (used in type comments)

from tuning.catalog import read_materials
from tuning.constraints import MATERIAL_KEY, MODE_KEY, QUALITY_KEY, Choices, apply_constraints, is_choice, wall_lines
from tuning.contracts import normalize_card
from tuning.facts import build_facts
from tuning.material_choice import choose_material
from tuning.planning import build_plan, find_conflicts, resolve_t
from tuning.rules import fired_rules, load_rules, requirement_keys
from tuning.space import Param, load_profile, load_search_space

_EPSILON = 1e-9
INFILL_PATTERN_DENSE_ABOVE_PCT = 25  # fdmprinter: infill_pattern = 'lines' if infill_sparse_density > 25 else 'grid'
ORIENTATION_CANDIDATE = "o1"


class Decisions(object):
    """Everything stage 2 decides for one card revision (and, on the second iteration, the validator's constraints)."""

    def __init__(self, card, geometry, materials_dir, feedback=None):
        # type: (dict, dict, str, Any) -> None
        self.card, self.warnings = normalize_card(card)
        self.geometry = geometry
        self.profile, self.space, self.rules = load_profile(), load_search_space(), load_rules()
        self.reasons = {rule["id"]: rule["reason"] for rule in self.rules}
        self.assumptions = []  # type: list
        self.unsatisfied = []  # type: list
        self.applied_constraints = []  # type: list
        self.choices = Choices()
        constraints = feedback.constraints if feedback is not None else []
        for constraint in constraints:
            if is_choice(constraint):
                self.choices.restrict(constraint["key"], constraint)
        self.choice = self._choose_material(read_materials(materials_dir, self.profile["filament_mm"]))
        self.material = self.choice.material
        context = self._context()
        self.params = {d["id"]: Param(d, context) for d in self.space["params"]}
        facts = build_facts(self.card, geometry)
        facts.update(self._material_facts())
        self.plan = build_plan(fired_rules(self.rules, facts), self.params, facts, context)
        passthrough, applied, constraint_unsatisfied = apply_constraints(
            [c for c in constraints if not is_choice(c)],
            self.plan,
            self.params,
            self.space,
            self.profile["line_width_mm"],
        )
        choice_constraints = [c for c in constraints if is_choice(c)]
        self.unsatisfied.extend(constraint_unsatisfied)
        self.unsatisfied.extend(self._plan_unsatisfied())
        self.mode = self._choose_mode()
        self.quality, self.layer_height_setting = self._choose_quality()
        self.settings = self._settings(passthrough)
        self.models = self._models(feedback)
        self.applied_constraints = [self._choice_record(c) for c in choice_constraints] + applied
        self._mode_assumptions()
        self.infeasible = self.choice.infeasible or bool(find_conflicts(self.plan)) or self._geometry_does_not_fit

    # --- material

    def _choose_material(self, materials):
        forced = self.choices.forced.get(MATERIAL_KEY)
        card = self.card
        if forced is not None:
            card = dict(card, material={"name": forced["value"], "requirement_id": None})
        allowed = {mid: m for mid, m in materials.items() if self.choices.permits(MATERIAL_KEY, mid)}
        choice, warnings = choose_material(card, allowed)
        self.warnings.extend(warnings)
        if forced is not None and choice.material.id == forced["value"]:
            choice.block["source"] = "constraint:" + forced["constraint_id"]
            choice.block["why"] = "материал задан ограничением этапа 3; " + choice.block["why"]
        self.assumptions.extend(choice.assumptions)
        self.unsatisfied.extend(choice.unsatisfied)
        return choice

    def _context(self):
        material = self.material
        default_speed = float(self.profile["defaults"]["speed_print"])
        speed = material.speed
        return {
            "profile": self.profile,
            "material": {
                "print_temperature": material.print_temperature,
                "speed": speed,
                "speed_floor": 0.5 * min(speed or default_speed, default_speed),
            },
            # The machine ceiling never forces a material below the temperature its own file asks for.
            "limits": {"temperature_max_c": max(self.profile["temperature_max_c"], material.print_temperature)},
        }

    def _material_facts(self):
        facts = {}
        if self.material.speed is not None:
            facts["material.speed"] = self.material.speed
        if self.material.cooling_pct is not None:
            facts["material.cooling_pct"] = self.material.cooling_pct
        return facts

    # --- requirement references for plan findings

    def _requirement_ids(self):
        ids = {}
        for requirement in self.card.get("requirements", []):
            ids.setdefault(requirement["key"], []).append(requirement["id"])
        return ids

    def _plan_unsatisfied(self):
        key_ids = self._requirement_ids()
        by_id = {rule["id"]: rule for rule in self.rules}

        def reference(rule_id):
            if rule_id is None or rule_id not in by_id:
                return rule_id or "rule:unknown"
            found = [i for key in requirement_keys(by_id[rule_id]) for i in key_ids.get(key, [])]
            return found[0] if found else "rule:" + rule_id

        found = []
        for item in self.plan["unsatisfied"]:
            for requirement_id in key_ids.get(item["requirement_key"], ["rule:" + item["rule_id"]]):
                found.append({"requirement_id": requirement_id, "why": item["why"]})
        for conflict in find_conflicts(self.plan):
            first, second = (conflict["rules"] + conflict["rules"])[:2]
            found.append(
                {
                    "requirement_id": reference(first),
                    "conflicts_with": reference(second),
                    "why": "ограничения %s и %s требуют несовместимых значений %s" % (first, second, conflict["param"]),
                }
            )
        return found

    def _chosen(self, key):
        if key == MODE_KEY:
            return self.mode["value"]
        if key == QUALITY_KEY:
            return self.quality["quality_type"]
        return self.material.id

    def _choice_record(self, constraint):
        """Checked against the final choice: a demanded mode the part does not fit is reported, not claimed."""
        chosen, operation, value = self._chosen(constraint["key"]), constraint["op"], constraint["value"]
        if operation not in ("eq", "ne", "in"):
            note = "op %s does not apply to %s" % (operation, constraint["key"])
        elif (operation == "eq" and chosen != value) or (operation == "ne" and chosen == value):
            note = "%s %s cannot be met: %s is chosen" % (constraint["key"], operation, chosen)
        elif operation == "in" and chosen not in value:
            note = "%s in %s cannot be met: %s is chosen" % (constraint["key"], value, chosen)
        else:
            return {"id": constraint["id"], "result": "applied", "why": constraint["reason"] or constraint["key"]}
        self.unsatisfied.append({"requirement_id": "constraint:" + constraint["id"], "why": note})
        return {"id": constraint["id"], "result": "not_applied", "why": note}

    # --- printing mode

    def _fits(self, mode):
        width, depth, height = self.geometry["bbox_mm"]["size"]
        spec = self.profile["modes"][mode]
        if height > spec["height_mm"] + _EPSILON:
            return False
        if spec["shape"] == "elliptic":
            semi_x, semi_y = self.profile["width_mm"] / 2.0, self.profile["depth_mm"] / 2.0
            return (width / 2.0 / semi_x) ** 2 + (depth / 2.0 / semi_y) ** 2 <= 1.0 + _EPSILON
        low, high = spec["usable_x_mm"]
        return width <= high - low + _EPSILON and depth <= self.profile["depth_mm"] + _EPSILON

    def _choose_mode(self):
        votes = list(self.plan["votes"])
        forced = self.choices.forced.get(MODE_KEY)
        if forced is not None:
            votes.append(
                {"mode": forced["value"], "weight": 1000.0, "rule_id": "constraint:" + forced["constraint_id"]}
            )
        weights, skipped = {}, []  # type: dict, list
        for vote in votes:
            mode = vote["mode"]
            if mode not in self.profile["modes"]:
                self.warnings.append("printing mode '%s' from %s is unknown, ignored" % (mode, vote["rule_id"]))
            elif not self.choices.permits(MODE_KEY, mode):
                skipped.append((vote, "запрещён ограничением этапа 3"))
            elif not self._fits(mode):
                skipped.append((vote, "деталь не помещается в область печати этого режима"))
            else:
                weights[mode] = weights.get(mode, 0.0) + vote["weight"]
        for vote, why in skipped:
            if vote["weight"] > 1.0:
                self.assumptions.append("режим %s не выбран: %s" % (vote["mode"], why))
        self._geometry_does_not_fit = not weights
        if not weights:
            fitting = [mode for mode in sorted(self.profile["modes"]) if self._fits(mode)]
            why = "габариты %s мм при ориентации «как загружено» не помещаются в выбранный режим" % (
                self.geometry["bbox_mm"]["size"],
            )
            why += "; помещаются в: %s" % ", ".join(fitting) if fitting else "; не помещаются ни в один режим"
            self.unsatisfied.append({"requirement_id": "GEOMETRY", "why": why})
            return {"value": "classic", "why": "деталь не помещается ни в один режим; оставлен 3D", "source": "default"}
        winner = max(sorted(weights), key=lambda mode: weights[mode])
        top = max((v for v in votes if v["mode"] == winner and v["mode"] in weights), key=lambda v: v["weight"])
        rule_id = top["rule_id"]
        if rule_id.startswith("constraint:"):
            return {"value": winner, "why": "режим задан ограничением этапа 3", "source": rule_id}
        if rule_id == "MODE-CARD-HINT":
            requirement_id = self.card.get("preferences", {}).get("printing_mode_requirement_id") or "printing_mode"
            return {"value": winner, "why": self.reasons[rule_id], "source": "requirement:" + requirement_id}
        return {"value": winner, "why": self.reasons[rule_id], "source": "rule:" + rule_id}

    # --- quality profile and layer height

    def _choose_quality(self):
        param = self.params["layer_height"]
        entry = self.plan["params"]["layer_height"]
        qualities = self.profile["qualities"]
        default = self.profile["default_quality"]
        t, rule_id = resolve_t(entry, param.clamped_t_of(qualities[default]["layer_height"]))
        target = param.v0 + t * (param.v1 - param.v0)
        allowed = [
            name
            for name in sorted(qualities)
            if self.choices.permits(QUALITY_KEY, name)
            and entry["lo"] - _EPSILON <= param.t_of(qualities[name]["layer_height"]) <= entry["hi"] + _EPSILON
        ]
        forced = self.choices.forced.get(QUALITY_KEY)
        if forced is not None and forced["value"] in qualities:
            return (
                {
                    "quality_type": forced["value"],
                    "why": "профиль задан ограничением этапа 3",
                    "source": "constraint:" + forced["constraint_id"],
                },
                None,
            )
        pool = allowed or [n for n in sorted(qualities) if self.choices.permits(QUALITY_KEY, n)] or sorted(qualities)
        name = min(pool, key=lambda n: (abs(qualities[n]["layer_height"] - target), qualities[n]["layer_height"]))
        layer = qualities[name]["layer_height"]
        layer_setting = None
        if not allowed:
            # No profile layer satisfies the hard limits: keep the nearest profile and set the layer explicitly.
            layer_setting = {"value": param.quantize(target), "rule_id": rule_id}
        if name == default and layer_setting is None:
            why = "профиль по умолчанию принтера: %s, слой %g мм" % (qualities[name]["label"], layer)
            if rule_id is not None:
                why += "; правило «%s» профиль не изменило: слой упёрся в допустимые пределы" % self._reason(rule_id)
            return {"quality_type": name, "why": why, "source": "default"}, layer_setting
        why = "%s; ближайший профиль — %s, слой %g мм" % (self._reason(rule_id), qualities[name]["label"], layer)
        return {"quality_type": name, "why": why, "source": _source(rule_id)}, layer_setting

    @property
    def layer_height(self):
        # type: () -> float
        if self.layer_height_setting is not None:
            return self.layer_height_setting["value"]
        return self.profile["qualities"][self.quality["quality_type"]]["layer_height"]

    # --- settings

    def _reason(self, rule_id):
        if rule_id is None:
            return "значение слайсера"
        if rule_id.startswith("constraint:"):
            return "ограничение этапа 3 (%s)" % rule_id
        return self.reasons.get(rule_id, rule_id)

    def _baseline_setting(self, key):
        values = self.profile["qualities"][self.quality["quality_type"]]["values"]
        return values.get(key, self.profile["defaults"].get(key))

    def _settings(self, passthrough):
        settings = {}
        if self.layer_height_setting is not None:
            rule_id = self.layer_height_setting["rule_id"]
            settings["layer_height"] = _setting(
                self.layer_height_setting["value"],
                "ни один профиль не укладывается в ограничения: " + self._reason(rule_id),
                _source(rule_id),
                "mm",
            )
        for param_id in sorted(self.params):
            if param_id != "layer_height":
                self._axis_setting(self.params[param_id], settings)
        density = settings.get("infill_sparse_density", {}).get(
            "value", self._baseline_setting("infill_sparse_density")
        )
        for definition in self.space["discrete"]:
            self._discrete_setting(definition, density, settings)
        for key, constraint in sorted(passthrough.items()):
            settings[key] = _setting(
                constraint["value"],
                "ограничение этапа 3: %s" % (constraint["reason"] or key),
                _source("constraint:" + constraint["id"]),
            )
        return settings

    def _axis_setting(self, param, settings):
        entry = self.plan["params"][param.id]
        baseline = self._baseline_value(param)
        t, rule_id = resolve_t(entry, param.clamped_t_of(baseline))
        value = param.value_at(t)
        if param.id == "skin_thickness":
            value, rule_id = self._enough_skin_layers(param, value, rule_id)
        if rule_id is None or abs(value - baseline) < _EPSILON:
            return
        why = "; ".join(self._reason(r) for r in _decisive_rules(entry, rule_id))
        if param.emit_as == "wall_thickness_from_lines":
            lines = int(value)
            settings[param.key] = _setting(
                round(lines * self.profile["line_width_mm"], 4),
                "%s; периметров: %d" % (why, lines),
                _source(rule_id),
                "mm",
            )
            return
        settings[param.key] = _setting(value, why, _source(rule_id), param.unit, param.scope)

    def _baseline_value(self, param):
        spec = param.baseline
        if "material" in spec:
            return float(self.material.print_temperature)
        value = float(self._baseline_setting(spec["setting"]))
        if spec.get("as") == "wall_lines":
            return float(wall_lines(value, self.profile["line_width_mm"]))
        return value

    def _enough_skin_layers(self, param, value, rule_id):
        rule = self.plan["min_layers"].get(param.id)
        if rule is None:
            return value, rule_id
        needed = rule["min"] * self.layer_height
        if value + _EPSILON >= needed:
            return value, rule_id
        return round(math.ceil(round(needed / param.step, 6)) * param.step, 4), rule["rule_id"]

    def _discrete_setting(self, definition, density, settings):
        key = definition["key"]
        if isinstance(key, dict):
            key = self.profile["modes"][self.mode["value"]][key["mode"]]
        baseline = self._discrete_baseline(definition["baseline"], density)
        chosen = self.plan["discrete"].get(definition["id"])
        value, rule_id = (chosen["value"], chosen["rule_id"]) if chosen else (baseline, None)
        allowed = self.plan["allowed"].get(definition["id"])
        banned = self.plan["banned"].get(definition["id"], [])
        if value in banned or (allowed is not None and value not in allowed):
            options = [c for c in definition["candidates"] if c not in banned and (allowed is None or c in allowed)]
            if not options:
                self.unsatisfied.append(
                    {"requirement_id": "discrete:" + definition["id"], "why": "все допустимые значения запрещены"}
                )
                return
            value, rule_id = options[0], self.plan["restricted_by"].get(definition["id"], rule_id)
        if value == baseline:
            return
        settings[key] = _setting(value, self._reason(rule_id), _source(rule_id), None, definition.get("scope"))

    def _discrete_baseline(self, spec, density):
        if spec.get("infill_pattern_formula"):
            return "lines" if density > INFILL_PATTERN_DENSE_ABOVE_PCT else "grid"
        if "mode" in spec:
            return self.profile["modes"][self.mode["value"]][spec["mode"]]
        return self._baseline_setting(spec["setting"])

    # --- models and assumptions

    def _models(self, feedback):
        size = self.geometry["bbox_mm"]["size"]
        spec = self.profile["modes"][self.mode["value"]]
        low, high = spec["usable_x_mm"]
        position = [round((low + high) / 2.0, 3), 0.0, round(size[2] / 2.0, 3)]
        self.orientation_assumption = (
            "ориентация «как загружено» и положение в центре рабочей области стола: нависаний в отчёте STL нет, "
            "поворот не подбирался"
        )
        self.assumptions.append(self.orientation_assumption)
        excluded = [e.get("candidate") for e in (feedback.excluded_orientations if feedback else [])]
        if ORIENTATION_CANDIDATE in excluded:
            self.unsatisfied.append(
                {"requirement_id": "orientation", "why": "единственный кандидат ориентации исключён этапом 3"}
            )
        quantity = self.card.get("preferences", {}).get("quantity", 1)
        if quantity > 1:
            self.assumptions.append("партия %d шт.: в проекте одна модель, копии в раскладку не добавлены" % quantity)
        files = self.card.get("inputs", {}).get("files", [])
        attachment = files[0]["path"].split(":", 1)[-1] if files else "model"
        return [
            {
                "id": "m1",
                "attachment_id": attachment,
                "extruder": 0,
                "orientation_candidate": ORIENTATION_CANDIDATE,
                "transform": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "position": position, "scale": [1, 1, 1]},
                "why": "модель стоит как в файле, в центре рабочей области стола режима %s" % spec["label"],
            }
        ]

    def _mode_assumptions(self):
        if self.mode["value"] == "classic":
            return
        self.assumptions.append(
            "диаметр основания 5D оставлен по умолчанию (%s мм): диаметр отверстия детали в отчёте STL не передан"
            % self.profile["defaults"]["cylindrical_mode_base_diameter"]
        )


def _source(rule_id):
    if rule_id is None:
        return "default"
    if ":" in rule_id:
        return rule_id
    return "rule:" + rule_id


def _decisive_rules(entry, rule_id):
    """The rule that set the value first, then the other rules that moved the same axis."""
    others = [r for r in entry["moving_rule_ids"] if r != rule_id]
    return [rule_id] + others


def _setting(value, why, source, unit=None, scope=None):
    entry = {"value": value, "why": why, "source": source}
    if unit:
        entry["unit"] = unit
    if scope:
        entry["scope"] = scope
    return entry
