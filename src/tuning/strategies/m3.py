"""M3: one scalar lambda moves every parameter along a cheap -> strong curve; bisection on lambda, then M1 refinements."""
from tuning.loop import TOLERANCE
from tuning.strategies.m1 import IntervalStrategy

SCALAR_STEPS = 3


def curve(plan, lam):
    # type: (dict, float) -> dict
    """Piecewise-linear path through (0: lower bound), (0.5: rule start), (1: upper bound) for every parameter."""
    points = {}
    for pid, entry in plan.items():
        start = min(max(entry["t0"], entry["lo"]), entry["hi"])
        if lam <= 0.5:
            points[pid] = entry["lo"] + 2.0 * lam * (start - entry["lo"])
        else:
            points[pid] = start + 2.0 * (lam - 0.5) * (entry["hi"] - start)
    return points


def _minimum_lambda_move(plan):
    # type: (dict) -> float
    """Smallest change of lambda that moves at least one parameter by one quantum."""
    moves = []
    for entry in plan.values():
        start = min(max(entry["t0"], entry["lo"]), entry["hi"])
        for slope in (2.0 * (start - entry["lo"]), 2.0 * (entry["hi"] - start)):
            if slope > TOLERANCE:
                moves.append(entry["step_t"] / slope)
    return min(moves) if moves else 1.0


class M3(IntervalStrategy):
    id = "m3"

    def propose(self, plan, state, feedback, iteration):
        # type: (dict, dict, object, int) -> tuple
        if feedback is None:
            points, state = super().propose(plan, state, None, iteration)
            state.update({"phase": "scalar", "lambda": [0.0, 1.0], "lam": 0.5, "scalar_steps": 0})
            return points, state
        if state["phase"] == "scalar":
            signals = [item["signal"] for found in feedback["signals"].values() for item in found]
            mixed = "too_weak" in signals and "too_costly" in signals
            if signals and not mixed and state["scalar_steps"] < SCALAR_STEPS:
                return self._move_lambda(plan, state, "too_weak" in signals)
            state = dict(state, phase="coordinate")
        return super().propose(plan, state, feedback, iteration)

    @staticmethod
    def _move_lambda(plan, state, weak):
        # type: (dict, dict, bool) -> tuple
        low, high = state["lambda"]
        lam = state["lam"]
        if weak:
            low = max(low, lam)
        else:
            high = min(high, lam)
        target = (low + high) / 2.0
        direction = 1.0 if weak else -1.0
        minimum = _minimum_lambda_move(plan)
        if (target - lam) * direction < minimum:
            target = lam + direction * minimum
        new_state = dict(state, lam=min(max(target, low), high), scalar_steps=state["scalar_steps"] + 1)
        new_state["lambda"] = [low, high]
        new_state["conflict"] = state["conflict"]
        if abs(new_state["lam"] - lam) < minimum * 0.999:
            new_state["conflict"] = {"param": "lambda", "why": "no distinct value left between the failing points and the bound"}
        points = curve(plan, new_state["lam"])
        new_state["points"] = dict(points)
        return points, new_state
