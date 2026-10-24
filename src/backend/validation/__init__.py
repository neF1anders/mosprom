"""Stage three: the check of a parameter set against the issued STE Slicer build."""

from __future__ import annotations

from ..domain.catalog import Catalog
from ..domain.errors import AppError
from ..domain.parameters import CheckResult, ParameterSet
from .checks import check_parameters
from .feedback import build_feedback, stage_two_errors


def check(parameter_set: ParameterSet, catalog: Catalog) -> CheckResult:
    """The findings and the feedback for the next pass.

    A set that breaks the contract itself (a key the slicer lacks, a wrong JSON type, a
    model off the plate) is a fault of parameter selection that no feedback can fix, so the
    pipeline stops with it instead of asking for another pass.
    """
    issues = check_parameters(parameter_set, catalog)
    broken = stage_two_errors(issues)
    if broken:
        details = "; ".join(issue.message for issue in broken)
        raise AppError(
            f"Подбор выдал набор, который слайсер не примет. {details}", "stage2_invalid"
        )
    return CheckResult(issues=issues, feedback=build_feedback(issues, parameter_set.iteration))
