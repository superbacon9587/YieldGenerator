import pytest
from statistics import median

from backend import economics
from backend import simulate as sim
from backend.schemas import LocationContext
from conftest import make_context
from test_simulate import block, request

CROP_PRICES = economics.load_crop_prices()
UTILITIES = economics.load_utility_prices()
DEFAULTS = economics.load_defaults()


def pump_cost(year, mode="current"):
    elec = UTILITIES.get(sim.ELECTRICITY_SERIES, year, mode)
    return economics.pumping_cost_per_af(DEFAULTS["well_lift_ft"], DEFAULTS["pump_efficiency"],
                                         elec.value, elec.unit)


def test_revenue_and_cost_formula(weather):
    resp = sim.simulate(request([block(crop="almonds", acres=40, start=1, end=12)]),
                        weather, make_context())
    y = resp.blocks[0].yearly[0]
    price = CROP_PRICES.get("almonds", y.year, "current")  # $ / LB
    assert y.revenue == pytest.approx(y.relative_yield / median(r.relative_yield for r in resp.blocks[0].yearly) * 2000 * 40 * price.value, abs=50)
    water = 0.5 * 50 + 0.5 * pump_cost(2004)
    assert y.cost == pytest.approx(3000 * 40 + y.water_applied_af * water, abs=50)
    assert y.profit == pytest.approx(y.revenue - y.cost, abs=1)


def test_tons_yield_priced_per_ton(weather):
    resp = sim.simulate(request([block(crop="walnuts", acres=10, start=1, end=12)]),
                        weather, make_context())
    y = resp.blocks[0].yearly[0]
    price = CROP_PRICES.get("walnuts", y.year, "current")
    assert economics.normalize_unit(price.unit) == "TON"
    assert y.revenue == pytest.approx(y.relative_yield / median(r.relative_yield for r in resp.blocks[0].yearly) * 1.9 * 10 * price.value, abs=10)


def test_pounds_yield_priced_per_ton_converts(weather):
    # Same walnuts, baseline given in pounds: 3800 lb = 1.9 tons.
    ctx = make_context()
    ctx["baseline_yields"]["walnuts"] = {"value": 3800.0, "unit": "LB / ACRE",
                                         "basis": "county", "source": "test"}
    lb = sim.simulate(request([block(crop="walnuts", start=1, end=12)]), weather, ctx)
    tons = sim.simulate(request([block(crop="walnuts", start=1, end=12)]), weather, make_context())
    assert lb.blocks[0].yearly[0].revenue == pytest.approx(tons.blocks[0].yearly[0].revenue, abs=1)


def test_bushels_use_crop_test_weight(weather):
    resp = sim.simulate(request([block(crop="corn", acres=15)]), weather, make_context())
    y = resp.blocks[0].yearly[0]
    price = CROP_PRICES.get("corn", y.year, "current")  # $ / BU
    assert y.revenue == pytest.approx(y.relative_yield / median(r.relative_yield for r in resp.blocks[0].yearly) * 160 * 15 * price.value, abs=10)


def test_missing_cost_gives_null_money_but_keeps_water(weather):
    resp = sim.simulate(request([block("b1", crop="almonds", acres=40, start=1, end=12),
                                 block("b2", crop="oats", acres=15, irrigation="sprinkler",
                                       start=11, end=4)]), weather, make_context())
    oats = resp.blocks[1]
    for y in oats.yearly:
        assert y.revenue is not None and y.cost is None and y.profit is None
        assert y.relative_yield > 0 and y.crop_water_use_in > 0
    assert any("b2 (oats) has no production cost" in a for a in resp.assumptions)
    # Farm totals add up the blocks that have money and say which were left out.
    almonds = resp.blocks[0].yearly
    for t, a in zip(resp.farm_totals, almonds):
        assert t.profit == pytest.approx(a.profit, abs=1)
    assert any("left out: b2 (oats)" in a for a in resp.assumptions)
    assert any("ranked by known-crop operating margin" in a for a in resp.assumptions)


def test_missing_baseline_yield_gives_null_money(weather):
    resp = sim.simulate(request([block(crop="processing_tomatoes", start=4, end=8)]),
                        weather, make_context())
    assert all(y.profit is None for y in resp.blocks[0].yearly)
    assert all(t.profit is None for t in resp.farm_totals)
    assert any("no baseline yield" in a for a in resp.assumptions)
    assert any("ranked by farm relative yield" in a for a in resp.assumptions)


def test_context_notes_and_location_are_copied(weather):
    ctx = make_context(county="Fresno", cost_region="San Joaquin Valley South",
                       data_quality=["Walnut yield uses the statewide median."])
    resp = sim.simulate(request([block()]), weather, ctx)
    assert resp.location.county == "Fresno"
    assert resp.location.cost_region == "San Joaquin Valley South"
    assert "Walnut yield uses the statewide median." in resp.assumptions


def test_outside_california_context(weather):
    ctx = make_context(state=None, county=None, in_california=False, cost_region=None,
                       data_quality=["Location is outside California."])
    resp = sim.simulate(request([block()]), weather, ctx)
    assert resp.location.county is None and resp.location.cost_region is None
    assert resp.blocks[0].yearly[0].profit is not None


def test_surface_water_share_changes_water_cost(weather):
    all_surface = sim.simulate(request([block(acres=10)], surface_water_share=1.0),
                               weather, make_context())
    y = all_surface.blocks[0].yearly[0]
    assert y.cost == pytest.approx(950 * 10 + y.water_applied_af * 50, abs=2)
    all_ground = sim.simulate(request([block(acres=10)], surface_water_share=0.0),
                              weather, make_context())
    g = all_ground.blocks[0].yearly[0]
    assert g.cost == pytest.approx(950 * 10 + g.water_applied_af * pump_cost(2004), abs=2)


def test_historical_prices_differ_by_year(weather):
    req = request([block(crop="almonds", start=1, end=12)], years=(2001, 2004))
    cur = sim.simulate(req, weather, make_context())
    hist = sim.simulate(req.model_copy(update={"price_mode": "historical"}),
                        weather, make_context())
    for c, h in zip(cur.blocks[0].yearly, hist.blocks[0].yearly):
        price = CROP_PRICES.get("almonds", h.year, "historical")
        assert h.revenue == pytest.approx(h.relative_yield / median(r.relative_yield for r in hist.blocks[0].yearly) * 2000 * 10 * price.value, abs=10)
        assert h.revenue != c.revenue
    assert any("that year's" in a for a in hist.assumptions)


def test_historical_missing_year_uses_nearest(weather):
    # Oats prices end in 2023; ask for a context that values oats and years with no price.
    ctx = make_context()
    ctx["production_costs"]["oats"] = {"cost_excl_water": 300.0, "unit": "$ / ACRE",
                                       "region": "x", "source": "test"}
    table = CROP_PRICES
    last = max(y for y in range(1980, 2030)
               if _has(table, "oats", y))
    first = min(y for y in range(1980, 2030) if _has(table, "oats", y))
    req = request([block(crop="oats", start=11, end=4)], years=(2001, 2004))
    hist = sim.simulate(req.model_copy(update={"price_mode": "historical"}), weather, ctx)
    assert all(y.revenue is not None for y in hist.blocks[0].yearly)
    if not all(_has(table, "oats", y) for y in range(2001, 2005)):
        assert any("nearest year" in a for a in hist.assumptions)
    assert first <= last


def _has(table, crop, year):
    try:
        table.get(crop, year, "historical")
        return True
    except economics.PriceNotFoundError:
        return False


def test_fallback_context_shape():
    ctx = sim._fallback_location_context(37.3, -120.48)
    LocationContext.model_validate(ctx)
    assert ctx["county"] == "Merced"
    assert sim.FALLBACK_NOTE in ctx["data_quality"]
    assert ctx["baseline_yields"]["corn"]["unit"] == "BU / ACRE"
    assert ctx["production_costs"]["corn"]["region"] == "San Joaquin Valley North"
    assert all("organic" not in c["region"].lower() for c in ctx["production_costs"].values())
    assert ctx["surface_water_price_per_af"] == 50


def test_fallback_context_runs_end_to_end(weather):
    resp = sim.simulate(request([block(crop="corn")]), weather,
                        sim._fallback_location_context(37.3, -120.48))
    assert resp.blocks[0].yearly[0].profit is not None
    assert sim.FALLBACK_NOTE in resp.assumptions
