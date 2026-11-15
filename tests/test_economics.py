import json

import pytest

from backend.economics import (
    CostComponent,
    CostIndexes,
    PriceNotFoundError,
    PriceTable,
    block_cost,
    convert_quantity,
    electricity_to_dollars_per_kwh,
    load_cost_components,
    load_cost_indexes,
    load_defaults,
    normalize_unit,
    pumping_cost_per_af,
    pumping_kwh_per_af,
    year_used,
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


def index_row(name, year, value, unit="index"):
    return {"index_name": name, "year": year, "value": value, "unit": unit, "source": "test", "source_url": ""}


@pytest.fixture
def indexes():
    return CostIndexes([
        index_row("fertilizer", 2020, 100.0), index_row("fertilizer", 2024, 150.0),
        index_row("wages", 2020, 100.0), index_row("wages", 2024, 120.0),
        index_row("diesel", 2020, 2.0, "$/gal"), index_row("diesel", 2024, 3.0, "$/gal"),
        index_row("electricity", 2020, 0.20, "$/kWh"), index_row("electricity", 2024, 0.25, "$/kWh"),
    ])


def component(name, basis, amount, index, base_year=2020, study_yield=2.0):
    return CostComponent(name, basis, amount, base_year, index, study_yield, "Test Valley")


@pytest.fixture
def components():
    # A 2020 study: fertilizer $100/acre, labor $200/acre, other $50/acre,
    # harvest $25/ton at 2 tons/acre ($50/acre), drip system $40/acre/yr.
    return [component("fertilizer", "per_acre", 100.0, "fertilizer"),
            component("labor", "per_acre", 200.0, "wages"),
            component("other", "per_acre", 50.0, "weighted_inputs"),
            component("harvest_haul", "per_ton", 25.0, "diesel"),
            component("irrigation_system_drip", "per_acre_system", 40.0, "weighted_inputs")]


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
    # 1 af x 200 ft x 1.024 / 0.6 = 341.33 kWh; at $0.25/kWh = $85.33
    assert pumping_kwh_per_af(200, 0.6) == pytest.approx(341.3333, abs=1e-4)
    assert pumping_cost_per_af(200, 0.6, 0.25) == pytest.approx(85.3333, abs=1e-4)
    assert pumping_cost_per_af(200, 0.6, 25, "cents per kilowatt-hour") == pytest.approx(85.3333, abs=1e-4)


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


# cost

def cost(components, indexes, year=2024, **kw):
    args = dict(acres=10, tons=30, irrigation="drip", surface_af=20, groundwater_af=20,
                surface_price_per_af=50, well_lift_ft=200, pump_efficiency=0.6, indexes=indexes, year=year)
    args.update(kw)
    return block_cost(components, **args)


def test_block_cost_formula(components, indexes):
    c = cost(components, indexes)
    # ratios 2024/2020: fertilizer 1.5, wages 1.2, diesel 1.5
    # weighted over the indexed rows by study dollars, harvest at 2 t/acre ($50/acre):
    # (100*1.5 + 200*1.2 + 50*1.5) / (100 + 200 + 50) = 465 / 350 = 1.328571
    assert c.weighted_ratio == pytest.approx(1.328571)
    # inputs: (100*1.5 + 200*1.2 + 50*1.328571) per acre = 456.43, x 10 acres
    assert c.inputs_per_acre == pytest.approx(456.43)
    assert c.inputs == pytest.approx(4564.30)
    assert c.harvest == pytest.approx(30 * 25 * 1.5)                 # per ton x tons x diesel ratio
    assert c.irrigation_system == pytest.approx(40 * 1.328571 * 10, abs=0.01)
    assert c.surface == pytest.approx(20 * 50)
    assert c.groundwater == pytest.approx(20 * 200 * 1.024 / 0.6 * 0.25, abs=0.01)
    assert c.total == round(c.inputs + c.harvest + c.irrigation_system + c.surface + c.groundwater)
    assert c.estimates == []


def test_block_cost_is_linear_in_acres_and_tons_when_unrounded(components, indexes):
    one = cost(components, indexes, acres=1, tons=3, surface_af=2, groundwater_af=2, rounded=False)
    ten = cost(components, indexes, acres=10, tons=30, surface_af=20, groundwater_af=20, rounded=False)
    assert ten.total == pytest.approx(10 * one.total)


def test_block_cost_base_year_is_unscaled(components, indexes):
    c = cost(components, indexes, year=2020, surface_af=0, groundwater_af=0)
    assert c.inputs_per_acre == 350 and c.harvest == 30 * 25 and c.irrigation_system == 400


def test_block_cost_other_irrigation_type_has_no_system_cost(components, indexes):
    assert cost(components, indexes, irrigation="flood").irrigation_system == 0


def test_block_cost_nearest_year_is_flagged(components, indexes):
    c = cost(components, indexes, year=2030)
    assert c.electricity.year == 2024 and c.electricity.is_estimate
    assert any("No electricity index for 2030; the nearest year (2024) is used" in e for e in c.estimates)
    assert c.inputs_per_acre == cost(components, indexes).inputs_per_acre


def test_block_cost_requires_placeholders_filled(components, indexes):
    with pytest.raises(ValueError, match="surface_water_price_per_af"):
        cost(components, indexes, surface_price_per_af=None)
    with pytest.raises(ValueError, match="well_lift_ft"):
        cost(components, indexes, well_lift_ft=None)


def test_year_used(indexes):
    assert year_used("current", 2001, indexes) == 2024
    assert year_used("historical", 2001, indexes) == 2001
    with pytest.raises(ValueError):
        year_used("average", 2001, indexes)


def test_real_cost_tables_load():
    idx = load_cost_indexes()
    assert idx.get("fertilizer", 2011).value == 100.0
    comps = load_cost_components()
    almonds = comps[("almonds", "Sacramento Valley")]
    assert {c.basis for c in almonds} == {"per_acre", "per_ton", "per_acre_system"}


# loaders

def test_load_defaults(tmp_path):
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps({"pump_efficiency": {"value": 0.6}, "well_lift_ft": {"value": None, "verify": True}}))
    assert load_defaults(p) == {"pump_efficiency": 0.6, "well_lift_ft": None}


def test_real_defaults_file_parses():
    d = load_defaults()
    assert d["pump_efficiency"] == 0.6
    assert d["price_mode"] == "current"
