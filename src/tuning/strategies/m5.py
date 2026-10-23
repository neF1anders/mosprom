"""M5: M1 that holds a parameter blamed both ways or stuck at a bound, and keeps moving the others."""
from tuning.strategies.m1 import IntervalStrategy


class M5(IntervalStrategy):
    id = "m5"
    defer_mixed = True
    defer_stuck = True
