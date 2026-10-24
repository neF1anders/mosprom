import pytest

from src.backend.domain.errors import AppError
from src.backend.validation import check

from .cases import parameter_set

pytestmark = pytest.mark.unit


def test_a_clean_set_passes_with_nothing_to_change(catalog):
    result = check(parameter_set("stage2_pla_speed_classic"), catalog)
    assert result.issues == [] and result.feedback.result == "ok"


def test_a_limit_breach_goes_back_to_selection(catalog):
    result = check(parameter_set("extra_above_max"), catalog)
    assert result.feedback.result == "needs_changes"
    assert [c.op for c in result.feedback.constraints] == ["max"]


def test_a_set_the_slicer_cannot_take_stops_the_pipeline(catalog):
    with pytest.raises(AppError) as refused:
        check(parameter_set("selftest_model_outside_bed"), catalog)
    assert refused.value.code == "stage2_invalid"
    assert refused.value.message.startswith("Подбор выдал набор, который слайсер не примет")
