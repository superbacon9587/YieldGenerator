import json

import pytest

from backend.economics import (
    BlockYear,
    PriceNotFoundError,
    PriceTable,
    block_profit,
    convert_quantity,
    electricity_to_dollars_per_kwh,
    load_defaults,
    load_production_costs,
    normalize_unit,
    pumping_cost_per_af,
    pumping_kwh_per_af,
)


@pytest.fixture
def crop_prices():
    return PriceTable([
        {"crop": "almonds", "year": 2020, "price": 1.70, "unit": "$ / LB"},
        {"crop": "almonds", "year": 2024, "price": 2.10, "unit": "$ / LB"},
        {"crop": "corn", "year": 2020, "price": 4.00, "unit": "$ / BU"},
        {"crop": "corn", "year": 2024, "price": 5.00, "unit": "$ / BU"},
        {"crop": "processing_tomatoes", "year": 2024, "price": 100.0, "unit": "$ / TON"},
    ], "crop")


@pytest.fixture
def utility_prices():
    return PriceTable([
        {"type": "electricity_commercial", "year": 2020, "price": 20.0, "unit": "cents per kilowatt-hour"},
        {"type": "electricity_commercial", "year": 2024, "price": 25.0, "unit": "cents per kilowatt-hour"},
    ], "type")


# units

@pytest.mark.parametrize("raw,expected", [
    ("$ / LB", "LB"), ("$ / TON", "TON"), ("$ / BU", "BU"), ("$ / CWT", "CWT"),
    ("tons/acre", "TON"), ("lb/acre", "LB"), ("bushels", "BU"),
    ("cents per kilowatt-hour", "CENTS/KWH"), ("$/kWh", "$/KWH"),
])
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected


def test_convert_mass_units():
    assert convert_quantity(1, "TON", "LB") == 2000
    assert convert_quantity(1, "TON", "CWT") == 20
    assert convert_quantity(500, "LB", "$ / CWT") == 5


def test_convert_bushels_is_crop_specific():
    assert convert_quantity(56, "LB", "BU", crop="corn") == 1
    assert convert_quantity(32, "LB", "BU", crop="oats") == 1
    assert convert_quantity(1, "TON", "BU", crop="corn") == pytest.approx(2000 / 56)


def test_bushels_without_known_crop_raises():
    with pytest.raises(ValueError):
        convert_quantity(1, "BU", "LB", crop="almonds")


def test_electricity_units():
    assert electricity_to_dollars_per_kwh(25, "cents per kilowatt-hour") == pytest.approx(0.25)
    assert electricity_to_dollars_per_kwh(0.25, "$/kWh") == 0.25
    with pytest.raises(ValueError):
        electricity_to_dollars_per_kwh(1, "$/MWh")


# pumping

def test_pumping_cost_formula():
    # 1 af x 200 ft x 1.02 / 0.6 = 340 kWh; at $0.25/kWh = $85
    assert pumping_kwh_per_af(200, 0.6) == pytest.approx(340)
    assert pumping_cost_per_af(200, 0.6, 0.25) == pytest.approx(85)
    assert pumping_cost_per_af(200, 0.6, 25, "cents per kilowatt-hour") == pytest.approx(85)


@pytest.mark.parametrize("eff", [0, -0.1, 1.5])
def test_pumping_rejects_bad_efficiency(eff):
    with pytest.raises(ValueError):
        pumping_kwh_per_af(100, eff)


# price lookup

def test_price_modes(crop_prices):
    assert crop_prices.get("almonds", 2020, "current").value == 2.10
    assert crop_prices.get("almonds", 2020, "current").year == 2024
    assert crop_prices.get("almonds", 2020, "historical").value == 1.70


def test_historical_missing_year_raises(crop_prices):
    with pytest.raises(PriceNotFoundError):
        crop_prices.get("almonds", 1990, "historical")


def test_unknown_crop_and_mode(crop_prices):
    with pytest.raises(PriceNotFoundError):
        crop_prices.get("kiwis", 2020)
    with pytest.raises(ValueError):
        crop_prices.get("almonds", 2020, "average")


# profit

def test_block_profit_almonds_current(crop_prices, utility_prices):
    block = BlockYear(crop="almonds", year=2020, acres=10, relative_yield=0.8,
                      baseline_yield=2000, yield_unit="lb",
                      surface_water_af=20, groundwater_af=20)
    r = block_profit(block, crop_prices, utility_prices, cost_excl_water_per_acre=3000,
                     surface_water_price_per_af=50, well_lift_ft=200, pump_efficiency=0.6,
                     price_mode="current")
    # revenue: 0.8 x 2000 lb x 10 ac x $2.10 = 33,600
    assert r["revenue"] == pytest.approx(33_600)
    # pumping: 340 kWh/af x $0.25 = $85/af; 20 af = 1,700
    assert r["groundwater_cost"] == pytest.approx(1_700)
    assert r["surface_water_cost"] == pytest.approx(1_000)
    assert r["operating_cost"] == pytest.approx(30_000)
    assert r["profit"] == pytest.approx(33_600 - 32_700)
    assert r["crop_price_year"] == 2024


def test_block_profit_historical_uses_that_years_prices(crop_prices, utility_prices):
    block = BlockYear("almonds", 2020, 10, 0.8, 2000, "lb", 0, 20)
    r = block_profit(block, crop_prices, utility_prices, 3000, 50, 200, 0.6, "historical")
    assert r["revenue"] == pytest.approx(0.8 * 2000 * 10 * 1.70)
    # 340 kWh/af x $0.20 x 20 af
    assert r["groundwater_cost"] == pytest.approx(340 * 0.20 * 20)


def test_block_profit_converts_yield_to_price_unit(crop_prices, utility_prices):
    # Corn yield in tons per acre, price in $/bu (56 lb/bu).
    block = BlockYear("corn", 2024, 1, 1.0, 5.6, "tons", 0, 0)
    r = block_profit(block, crop_prices, utility_prices, 0, 0, 0)
    assert r["production"] == pytest.approx(5.6 * 2000 / 56)
    assert r["revenue"] == pytest.approx(200 * 5.0)

    # Tomato yield in lb, price in $/ton.
    block = BlockYear("processing_tomatoes", 2024, 1, 1.0, 100_000, "lb", 0, 0)
    r = block_profit(block, crop_prices, utility_prices, 0, 0, 0)
    assert r["revenue"] == pytest.approx(50 * 100)


def test_block_profit_requires_placeholders_filled(crop_prices, utility_prices):
    block = BlockYear("almonds", 2024, 1, 1.0, 2000, "lb")
    with pytest.raises(ValueError, match="surface_water_price_per_af"):
        block_profit(block, crop_prices, utility_prices, 0, None, 100)
    with pytest.raises(ValueError, match="well_lift_ft"):
        block_profit(block, crop_prices, utility_prices, 0, 50, None)


# loaders

def test_load_production_costs_takes_latest_study(tmp_path):
    p = tmp_path / "costs.csv"
    p.write_text(
        "crop,study_year,region,cost_per_acre,water_cost_per_acre,cost_excl_water,unit,source\n"
        "almonds,2019,SJV North,3000,500,2500,$/acre,a.pdf p. 5\n"
        "almonds,2023,SJV North,3600,600,3000,$/acre,b.pdf p. 6\n"
        "walnuts,2022,SJV North,,,,$/acre,c.pdf page not found\n"
    )
    assert load_production_costs(p) == {"almonds": 3000.0}


def test_load_defaults(tmp_path):
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps({"pump_efficiency": {"value": 0.6}, "well_lift_ft": {"value": None, "verify": True}}))
    assert load_defaults(p) == {"pump_efficiency": 0.6, "well_lift_ft": None}


def test_real_defaults_file_parses():
    d = load_defaults()
    assert d["pump_efficiency"] == 0.6
    assert d["price_mode"] == "current"
