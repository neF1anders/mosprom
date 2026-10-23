"""M0: one-shot rules, the verdict is ignored. Baseline for every comparison."""


class M0(object):
    id = "m0"

    def propose(self, plan, strategy_state, verdict, iteration):
        # type: (dict, dict, object, int) -> tuple
        """Return ({param_id: t}, new strategy state); plan maps param ids to t0/lo/hi."""
        points = {param_id: min(max(entry["t0"], entry["lo"]), entry["hi"]) for param_id, entry in plan.items()}
        return points, {}
