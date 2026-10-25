from __future__ import annotations

from ..domain.catalog import Catalog
from ..domain.errors import AppError
from ..domain.parameters import CheckResult, ParameterSet
from .checks import check_parameters
from .feedback import build_feedback, stage_two_errors


def check(parameter_set: ParameterSet, catalog: Catalog) -> CheckResult:
    """Замечания и обратная связь."""
    issues = check_parameters(parameter_set, catalog)
    broken = stage_two_errors(issues)
    if broken:
        details = "; ".join(issue.message for issue in broken)
        raise AppError(
            f"Подбор выдал набор, который слайсер не примет. {details}", "stage2_invalid"
        )
    return CheckResult(issues=issues, feedback=build_feedback(issues, parameter_set.iteration))
