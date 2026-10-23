"""Brute-force oracle over a grid of the allowed parameter box (development stand only)."""

import itertools
from typing import Any  # noqa: F401  (used in type comments)

LEVELS = 5


def grid_levels(preparation):
    # type: (Any) -> dict
    """{param_id: [(value, u)]}: LEVELS equally spaced t inside the plan interval, quantised as the slicer sees them."""
    levels = {}
    for param_id, param in preparation.params.items():
        entry = preparation.plan["params"][param_id]
        values = set(
            param.value_at(entry["lo"] + (entry["hi"] - entry["lo"]) * k / (LEVELS - 1.0)) for k in range(LEVELS)
        )
        levels[param_id] = [(value, param.t_of(value)) for value in sorted(values)]
    return levels


def evaluate_grid(preparation, unit_metrics):
    # type: (Any, Any) -> list
    """Rows (S, Q, T, values_tuple) for every grid point; values follow sorted parameter ids.

    `unit_metrics` maps {param_id: u} to (S, Q, T); it must be noise-free.
    """
    levels = grid_levels(preparation)
    ids = sorted(levels)
    rows = []
    for combination in itertools.product(*[levels[param_id] for param_id in ids]):
        s, q, t = unit_metrics(dict(zip(ids, [u for _, u in combination])))
        rows.append((s, q, t, tuple(value for value, _ in combination)))
    return rows


def maxima(rows):
    # type: (list) -> tuple
    return max(row[0] for row in rows), max(row[1] for row in rows)


def best_feasible(rows, s_min, q_min):
    # type: (list, float, float) -> Any
    """The cheapest row with S >= s_min and Q >= q_min (ties: smaller value tuple), or None."""
    feasible = [row for row in rows if row[0] >= s_min and row[1] >= q_min]
    if not feasible:
        return None
    return min(feasible, key=lambda row: (row[2], row[3]))
