from decimal import Decimal

import pytest

from src.backend.domain.units import convert, numbers, quantity_key

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "value,source,target,expected",
    [
        ("2.5", "inch", "mm", "63.5"),
        ("1", "kgf", "N", "9.80665"),
        ("25", "Н·м", "N·mm", "25000"),
        ("1.05", "g/cm³", "kg/m3", "1050"),
        ("100", "°C", "K", "373.15"),
        ("212", "°F", "°C", "100"),
        ("2", "bar", "kPa", "200"),
    ],
)
def test_conversions(value, source, target, expected):
    assert convert(Decimal(value), source, target) == Decimal(expected)


@pytest.mark.parametrize(
    "source,target", [("kg", "N"), ("mm", "N"), ("°C", "mm"), ("parsec", "mm")]
)
def test_mass_is_not_force_and_unknown_units_fail(source, target):
    with pytest.raises(ValueError):
        convert(Decimal(1), source, target)


def test_numbers_keep_ranges_and_decimal_commas():
    assert numbers("от 10 до 70, допуск 0,05 и -20") == [
        Decimal("10"),
        Decimal("70"),
        Decimal("0.05"),
        Decimal("-20"),
    ]
    assert numbers("10-70") == [Decimal("10"), Decimal("70")]


def test_numbers_read_both_ends_of_a_dotted_range_but_not_a_dotted_version():
    assert numbers("-10..70") == [Decimal("-10"), Decimal("70")]
    assert numbers("1.5.7") == [Decimal("1.5")]
    assert numbers("v.2") == []


def test_equivalent_quantities_compare_equal():
    assert quantity_key("100", "мм") == quantity_key("10", "см")
    assert quantity_key("25", "Н·м") == quantity_key("25000", "Н·мм")
    assert quantity_key("25", "Н·м") != quantity_key("75", "Н·м")
    assert quantity_key("PA12", None) == quantity_key("pa12 ", None)
