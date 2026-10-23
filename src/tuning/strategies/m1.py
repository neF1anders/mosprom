"""M1: per-parameter interval + bisection (hypothesis H1 of the stage owner)."""
from tuning.loop import TOLERANCE


class IntervalStrategy(object):
    """Base: keeps [lo, hi] per parameter; subclasses choose how far to step inside it."""
    id = "m1"
    adaptive = True
    # M1 as specified declares a conflict when one parameter is blamed both ways; M5 holds that parameter instead.
    defer_mixed = False

    def propose(self, plan, state, feedback, iteration):
        # type: (dict, dict, object, int) -> tuple
        if feedback is None:
            points = {pid: min(max(entry["t0"], entry["lo"]), entry["hi"]) for pid, entry in plan.items()}
            return points, {"points": dict(points), "intervals": {pid: [e["lo"], e["hi"]] for pid, e in plan.items()},
                            "conflict": None}
        state = {key: (dict(value) if isinstance(value, dict) else value) for key, value in state.items()}
        points, intervals = state["points"], state["intervals"]
        self.observe(state, feedback, points)
        for pid, found in sorted(feedback["signals"].items()):
            if pid not in points:
                continue
            moved = self.step(pid, points[pid], intervals[pid], found, plan[pid], feedback, state, iteration)
            if moved is None:
                continue
            points[pid] = moved
        return dict(points), state

    def step(self, pid, current, interval, found, bounds, feedback, state, iteration):
        # type: (str, float, list, list, dict, dict, dict, int) -> object
        """Update the interval from the signals; return the new t or None when nothing can change."""
        weak = any(item["signal"] == "too_weak" for item in found)
        costly = any(item["signal"] == "too_costly" for item in found)
        if not (weak or costly):
            return None
        if weak and costly:
            if self.defer_mixed:
                return None
            self.flag_conflict(state, pid, "validator reports both too_weak and too_costly")
            return None
        lo, hi = interval
        direction = 1 if weak else -1
        if weak:
            lo = max(lo, current)
        else:
            hi = min(hi, current)
        interval[0], interval[1] = lo, hi
        room = (hi - current) if weak else (current - lo)
        quantum = bounds["step_t"]
        if room < quantum - TOLERANCE:
            self.flag_conflict(state, pid, "no distinct value left between the failing points and the bound")
            return None
        target = self.target(pid, current, lo, hi, weak, found, feedback, state)
        if (target - current) * direction < quantum - TOLERANCE:
            target = current + direction * quantum
        return min(max(target, lo), hi)

    def observe(self, state, feedback, points):
        # type: (dict, dict, dict) -> None
        """Hook: record what the validator said about `points` before the interval update."""

    def target(self, pid, current, lo, hi, weak, found, feedback, state):
        # type: (str, float, float, float, bool, list, dict, dict) -> float
        return (lo + hi) / 2.0

    @staticmethod
    def flag_conflict(state, pid, why):
        if not state["conflict"]:
            state["conflict"] = {"param": pid, "why": why}


class M1(IntervalStrategy):
    pass
