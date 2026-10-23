"""Deterministic validator STUB for development of the tuning loop (not the real validator).

Worlds: w1 monotone and separable, w2 with interactions, w3 non-monotone with noise and without severity.
The specification of the metrics and thresholds was fixed before any strategy was run on it.
"""
import random

from tuning.experiments import oracle

WORLDS = ("w1", "w2", "w3")
NOISE_SIGMA = 0.03
THRESHOLD_SLACK = 1.3
MAX_SHARE_OF_GRID_OPTIMUM = 0.85
_STRENGTH_BASE = {"wall_line_count": 0.30, "infill_density": 0.20, "skin_thickness": 0.15,
                  "print_temperature": 0.15, "layer_height": 0.10, "print_speed": 0.10}
_TIME_BASE = {"layer_height": 0.35, "wall_line_count": 0.15, "infill_density": 0.20, "skin_thickness": 0.10,
              "print_speed": 0.20, "print_temperature": 0.0}
_QUALITY_BASE = {"w1": {"layer_height": 0.70, "print_speed": 0.30, "print_temperature": 0.0},
                 "w2": {"layer_height": 0.65, "print_speed": 0.25, "print_temperature": 0.10},
                 "w3": {"layer_height": 0.65, "print_speed": 0.25, "print_temperature": 0.10}}


def _jittered(base, rng):
    # type: (dict, object) -> dict
    """Each weight times (1 + 0.10 * (2r - 1)), drawn in sorted id order, renormalised to sum 1."""
    raw = {}
    for param_id in sorted(base):
        raw[param_id] = base[param_id] * (1.0 + 0.10 * (2.0 * rng.random() - 1.0))
    scale = 1.0 / sum(raw.values())
    return {param_id: weight * scale for param_id, weight in raw.items()}


def _requirement(card, key):
    # type: (dict, str) -> object
    for requirement in card.get("requirements", []):
        if requirement.get("key") == key:
            return requirement
    return None


class StubValidator(object):
    """Computes S (strength), Q (surface quality), T (time cost) of a param_set and judges it against thresholds."""

    def __init__(self, world, seed, preparation, geometry, card):
        # type: (str, int, object, dict, dict) -> None
        if world not in WORLDS:
            raise ValueError("unknown world '%s', available: %s" % (world, ", ".join(WORLDS)))
        self.world, self.seed, self.preparation, self.card = world, seed, preparation, card
        self.infill_share = min(1.0, (geometry["volume_mm3"] / geometry["surface_area_mm2"]) / 5.0)
        rng = random.Random(seed)
        strength = dict(_STRENGTH_BASE, infill_density=_STRENGTH_BASE["infill_density"] * self.infill_share)
        time_cost = dict(_TIME_BASE, infill_density=_TIME_BASE["infill_density"] * self.infill_share)
        self.strength_weights = _jittered(strength, rng)
        self.time_weights = _jittered(time_cost, rng)
        self.quality_weights = _jittered(_QUALITY_BASE[world], rng)
        self._time_norm = (0.2 + 0.25 + 0.35 * self.infill_share + 0.2)
        self.restart()
        self._set_thresholds()

    def restart(self):
        # type: () -> None
        """Reset the noise stream so that every run of a cell sees the same validator."""
        self._noise = random.Random(self.seed + 1000)

    def unit_metrics(self, u):
        # type: (dict) -> tuple
        """Noise-free (S, Q, T) from normalised parameters u = {param_id: [0, 1]}."""
        ws, wq, wt = self.strength_weights, self.quality_weights, self.time_weights
        strength = sum(ws[param_id] * u[param_id] for param_id in ws)
        if self.world == "w1":
            return strength, wq["layer_height"] * u["layer_height"] + wq["print_speed"] * u["print_speed"], \
                sum(wt[param_id] * u[param_id] for param_id in wt)
        layer, wall, infill, skin = u["layer_height"], u["wall_line_count"], u["infill_density"], u["skin_thickness"]
        temp, speed = u["print_temperature"], u["print_speed"]
        if self.world == "w3":
            strength += ws["print_temperature"] * ((1.0 - ((temp - 0.6) / 0.6) ** 2) - temp)
            strength -= 0.10 * max(0.0, infill - 0.7) / 0.3
        strength = (strength + 0.25 * layer * wall + 0.15 * infill * temp + 0.10 * skin * layer) / 1.5
        quality = (wq["layer_height"] * layer + wq["print_speed"] * speed
                   + wq["print_temperature"] * (1.0 - 2.0 * abs(temp - 0.5)))
        cost = ((0.2 + 0.25 * wall + 0.35 * self.infill_share * infill + 0.2 * skin)
                * (0.3 + 0.7 * layer) * (0.4 + 0.6 * speed) / self._time_norm)
        return strength, quality, cost

    def metrics(self, values):
        # type: (dict) -> dict
        """Noise-free {"S", "Q", "T"} from slicer-side values {param_id: value}."""
        u = {param_id: self.preparation.params[param_id].t_of(value) for param_id, value in values.items()}
        strength, quality, cost = self.unit_metrics(u)
        return {"S": strength, "Q": quality, "T": cost}

    def values_of(self, param_set):
        # type: (dict) -> dict
        """{param_id: value} of the proposed point, read through the t stored with the first key of each parameter."""
        by_key = {setting["key"]: setting for setting in param_set["settings"]}
        mode = param_set["printing_mode"]["value"]
        return {param_id: param.value_at(by_key[self._key_of(param_id, mode)]["t"])
                for param_id, param in self.preparation.params.items()}

    def verdict(self, param_set):
        # type: (dict) -> dict
        values = self.values_of(param_set)
        mode = param_set["printing_mode"]["value"]
        exact = self.metrics(values)
        strength, quality, cost = exact["S"], exact["Q"], exact["T"]
        if self.world == "w3":
            strength += self._noise.gauss(0.0, NOISE_SIGMA)
            quality += self._noise.gauss(0.0, NOISE_SIGMA)
            cost *= 1.0 + self._noise.gauss(0.0, NOISE_SIGMA)
        violations = {"S": max(0.0, (self.s_min - strength) / self.s_min),
                      "Q": max(0.0, (self.q_min - quality) / self.q_min),
                      "T": max(0.0, (cost - self.t_max) / self.t_max)}
        u = {param_id: self.preparation.params[param_id].t_of(value) for param_id, value in values.items()}
        issues = []
        for metric in ("S", "Q", "T"):
            if violations[metric] > 0.0:
                for param_id in self._blamed(metric, u):
                    issues.append(self._issue(len(issues) + 1, metric, param_id, mode, violations[metric]))
        return {"schema": "verdict/0", "ok": not issues, "score": 1.0 - sum(violations.values()) / 3.0,
                "issues": issues, "vetoes": []}

    def _issue(self, number, metric, param_id, mode, violation):
        # type: (int, str, str, str, float) -> dict
        issue = {"id": "V%d" % number, "key": self._key_of(param_id, mode),
                 "signal": "too_costly" if metric == "T" else "too_weak", "hard": metric != "T",
                 "message": "stub %s violated by %.3f, blamed parameter %s" % (metric, violation, param_id)}
        if metric != "T":
            issue["requirement_id"] = self._requirement_id(metric)
        if self.world != "w3":
            issue["severity"] = min(1.0, violation)
        return issue

    def _blamed(self, metric, u):
        # type: (str, dict) -> list
        if metric == "T":
            shares = {param_id: self.time_weights[param_id] * u[param_id] for param_id in self.time_weights}
        else:
            weights = self.strength_weights if metric == "S" else self.quality_weights
            shares = {param_id: weights[param_id] * (1.0 - u[param_id]) for param_id in weights}
        return sorted(shares, key=lambda param_id: (-shares[param_id], param_id))[:2]

    def _requirement_id(self, metric):
        # type: (str) -> str
        requirements = self.card.get("requirements", [])
        if metric == "S":
            found = _requirement(self.card, "high_stiffness")
            if found is None:
                found = next((r for r in requirements if r.get("hard")), None)
            return found["id"] if found else "S"
        found = _requirement(self.card, "dimensional_tol_mm") or _requirement(self.card, "no_visible_layers")
        return found["id"] if found else "Q"

    def _key_of(self, param_id, mode):
        # type: (str, str) -> str
        param = self.preparation.params[param_id]
        return param.emit["keys"][0] if param.emit else param.keys[mode][0]

    def _set_thresholds(self):
        # type: () -> None
        rows = oracle.evaluate_grid(self.preparation, self.unit_metrics)
        max_s, max_q = oracle.maxima(rows)
        self.s_min = min(self._base_strength_threshold(), MAX_SHARE_OF_GRID_OPTIMUM * max_s)
        self.q_min = min(self._base_quality_threshold(), MAX_SHARE_OF_GRID_OPTIMUM * max_q)
        best = oracle.best_feasible(rows, self.s_min, self.q_min)
        if best is None:
            raise AssertionError("oracle found no feasible point in world %s seed %d" % (self.world, self.seed))
        self.t_opt = best[2]
        self.opt_values = dict(zip(sorted(self.preparation.params), best[3]))
        self.t_max = THRESHOLD_SLACK * self.t_opt

    def _base_strength_threshold(self):
        # type: () -> float
        threshold = 0.40
        if _requirement(self.card, "high_stiffness") is not None:
            threshold += 0.10
        if self.card.get("part", {}).get("load") in ("cyclic", "impact"):
            threshold += 0.08
        if (self.card.get("preferences", {}).get("priority") or [None])[0] == "strength":
            threshold += 0.07
        return threshold

    def _base_quality_threshold(self):
        # type: () -> float
        threshold = 0.30
        tolerance = _requirement(self.card, "dimensional_tol_mm")
        if tolerance is not None:
            if tolerance["value"] <= 0.15:
                threshold += 0.35
            elif tolerance["value"] <= 0.3:
                threshold += 0.15
        if _requirement(self.card, "no_visible_layers") is not None:
            threshold += 0.20
        return threshold
