from tuning.errors import TuningError
from tuning.strategies.m0 import M0
from tuning.strategies.m1 import M1

REGISTRY = {"m0": M0, "m1": M1}


def get_strategy(strategy_id):
    # type: (str) -> object
    try:
        return REGISTRY[strategy_id]()
    except KeyError:
        raise TuningError("unknown strategy '%s', available: %s" % (strategy_id, ", ".join(sorted(REGISTRY))))
