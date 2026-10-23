"""M4: three ready candidates (balance / strong / fast), evaluated in turn, then one refinement between the best two."""

from typing import Any  # noqa: F401  (used in type comments)

from tuning.loop import TOLERANCE

_SHIFT = 0.3


def _clamp(plan, shift):
    # type: (dict, float) -> dict
    return {pid: min(max(min(max(e["t0"], e["lo"]), e["hi"]) + shift, e["lo"]), e["hi"]) for pid, e in plan.items()}


def _quality(result):
    score = result["score"] if result["score"] is not None else float("-inf")
    return (score, -result["issue_count"], -result["severity_sum"])


class M4(object):
    id = "m4"
    adaptive = True

    def propose(self, plan, state, feedback, iteration):
        # type: (dict, dict, Any, int) -> tuple
        if feedback is None:
            candidates = {"balance": _clamp(plan, 0.0), "strong": _clamp(plan, _SHIFT), "fast": _clamp(plan, -_SHIFT)}
            return dict(candidates["balance"]), {
                "candidates": candidates,
                "order": ["balance"],
                "results": [],
                "points": dict(candidates["balance"]),
                "conflict": None,
            }
        state = dict(state)
        results = list(state["results"])
        results.append(self._summarise(feedback, state["points"]))
        order = list(state["order"])
        if len(order) == 1:
            order += ["fast", "strong"] if self._only_costly(feedback) else ["strong", "fast"]
        state["results"], state["order"] = results, order
        if len(results) < len(order):
            points = state["candidates"][order[len(results)]]
        else:
            points = self._refine(results)
        state["points"] = dict(points)
        return points, state

    @staticmethod
    def _summarise(feedback, points):
        severities = [item.get("severity") or 0.0 for found in feedback["signals"].values() for item in found]
        return {
            "points": dict(points),
            "score": feedback["score"],
            "issue_count": len(severities),
            "severity_sum": sum(severities),
        }

    @staticmethod
    def _only_costly(feedback):
        signals = [item["signal"] for found in feedback["signals"].values() for item in found]
        return bool(signals) and all(signal == "too_costly" for signal in signals)

    @staticmethod
    def _refine(results):
        # type: (list) -> dict
        """Midpoint between the two best candidates; the best one itself when they coincide."""
        ranked = sorted(results, key=_quality, reverse=True)
        first, second = ranked[0]["points"], ranked[1]["points"]
        return {
            pid: (first[pid] + second[pid]) / 2.0 if abs(first[pid] - second[pid]) > TOLERANCE else first[pid]
            for pid in first
        }
