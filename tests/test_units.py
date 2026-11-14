import pytest

from backend import units
from backend.units import to_tons_per_acre


def test_pounds_divide_by_2000():
    assert to_tons_per_acre(2400, "LB / ACRE", "almonds") == pytest.approx(1.2)


def test_corn_bushels_use_56_lb():
    # 160 bu x 56 lb / 2000 = 4.48 tons
    assert to_tons_per_acre(160, "BU / ACRE", "corn") == pytest.approx(4.48)


def test_oats_bushels_use_32_lb():
    # 80 bu x 32 lb / 2000 = 1.28 tons
    assert to_tons_per_acre(80, "BU / ACRE", "oats") == pytest.approx(1.28)


def test_wheat_bushels_use_60_lb():
    assert to_tons_per_acre(100, "BU / ACRE", "wheat") == pytest.approx(3.0)


def test_tons_unchanged():
    assert to_tons_per_acre(1.9, "TONS / ACRE", "walnuts") == pytest.approx(1.9)


def test_spacing_and_case_are_forgiven():
    assert to_tons_per_acre(2000, "lb/acre", "almonds") == pytest.approx(1.0)


def test_unknown_unit_raises():
    with pytest.raises(ValueError, match="Unknown yield unit 'CWT / ACRE'"):
        to_tons_per_acre(10, "CWT / ACRE", "processing_tomatoes")


def test_bushels_of_crop_without_weight_raise():
    with pytest.raises(ValueError, match="No bushel weight for crop 'almonds'"):
        to_tons_per_acre(10, "BU / ACRE", "almonds")


def test_conversion_text():
    assert units.conversion_text("LB / ACRE", "almonds") == "lb / 2000"
    assert units.conversion_text("BU / ACRE", "corn") == "bu x 56 lb / 2000"
    assert units.conversion_text("TONS / ACRE", "walnuts") == "already tons"
