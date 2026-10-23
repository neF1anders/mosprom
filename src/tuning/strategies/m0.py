"""M0: one-shot rules, the verdict is ignored. Baseline for every comparison."""

from typing import Any  # noqa: F401  (used in type comments)


class M0(object):
    id = "m0"
    # A rejected one-shot proposal ends the run: the baseline never revises.
    adaptive = False

    def propose(self, plan, state, feedback, iteration):
        # type: (dict, dict, Any, int) -> tuple
        """Return ({param_id: t}, new strategy state); plan maps param ids to t0/lo/hi."""
        points = {param_id: min(max(entry["t0"], entry["lo"]), entry["hi"]) for param_id, entry in plan.items()}
        return points, {"points": dict(points), "conflict": None}
