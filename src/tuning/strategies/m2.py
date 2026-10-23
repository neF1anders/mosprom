"""M2: M1 with an adaptive step: severity sets the fraction of the way, score improvement rate scales it (secant)."""

from tuning.strategies.m1 import IntervalStrategy

_MIN_FRACTION, _MAX_FRACTION = 0.3, 0.95
_MIN_SCALE = 0.3


class M2(IntervalStrategy):
    id = "m2"

    def observe(self, state, feedback, points):
        # type: (dict, dict, dict) -> None
        trace = list(state.get("trace", []))
        trace.append({"score": feedback["score"], "points": dict(points)})
        state["trace"] = trace

    def target(self, pid, current, lo, hi, weak, found, feedback, state):
        # type: (str, float, float, float, bool, list, dict, dict) -> float
        span = (hi - current) if weak else (lo - current)
        severities = [item["severity"] for item in found if item.get("severity") is not None]
        fraction = 0.5
        if severities:
            fraction = min(max(_MIN_FRACTION + 0.7 * max(severities), _MIN_FRACTION), _MAX_FRACTION)
        scale = self._secant_scale(state, abs(span) * fraction * len(feedback["signals"]))
        return current + span * fraction * scale

    @staticmethod
    def _secant_scale(state, planned_distance):
        # type: (dict, float) -> float
        """Shrink the step when the last move already improved the score fast enough to close the gap."""
        trace = state["trace"]
        if len(trace) < 2 or planned_distance <= 0 or None in (trace[-1]["score"], trace[-2]["score"]):
            return 1.0
        moved = sum(abs(trace[-1]["points"][pid] - trace[-2]["points"][pid]) for pid in trace[-1]["points"])
        gain = trace[-1]["score"] - trace[-2]["score"]
        if moved <= 0 or gain <= 0:
            return 1.0
        needed = (1.0 - trace[-1]["score"]) / (gain / moved)
        return min(max(needed / planned_distance, _MIN_SCALE), 1.0)
