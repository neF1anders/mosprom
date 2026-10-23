from tuning.errors import TuningError
from tuning.strategies.m0 import M0

REGISTRY = {"m0": M0}


def get_strategy(strategy_id):
    # type: (str) -> object
    try:
        return REGISTRY[strategy_id]()
    except KeyError:
        raise TuningError("unknown strategy '%s', available: %s" % (strategy_id, ", ".join(sorted(REGISTRY))))
