from tuning.errors import TuningError
from tuning.strategies.m0 import M0
from tuning.strategies.m1 import M1
from tuning.strategies.m2 import M2
from tuning.strategies.m3 import M3
from tuning.strategies.m4 import M4

REGISTRY = {"m0": M0, "m1": M1, "m2": M2, "m3": M3, "m4": M4}


def get_strategy(strategy_id):
    # type: (str) -> object
    try:
        return REGISTRY[strategy_id]()
    except KeyError:
        raise TuningError("unknown strategy '%s', available: %s" % (strategy_id, ", ".join(sorted(REGISTRY))))
