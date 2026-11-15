import csv
from pathlib import Path
from statistics import median

import pytest

from backend import economics
from backend import simulate as sim
from backend.schemas import LocationContext
from conftest import make_context
from test_simulate import block, request

ROOT = Path(__file__).resolve().parent.parent
CROP_PRICES = economics.load_crop_prices()
DEFAULTS = economics.load_defaults()
COMPONENTS = list(csv.DictReader((ROOT / "data/prices/cost_components.csv").open()))
INDEX = {(r["index_name"], int(r["year"])): float(r["value"])
         for r in csv.DictReader((ROOT / "data/prices/cost_indexes.csv").open())}
LATEST = max(y for _, y in INDEX)


def pump_cost(year):
    return DEFAULTS["well_lift_ft"] * 1.024 / DEFAULTS["pump_efficiency"] * INDEX[("electricity", year)]


def expected_cost(crop, region, acres, tons, irrigation, surface_af, ground_af, year, surface_price=50.0):
    """The requested formula, written out independently of backend/economics.py."""
    rows = [r for r in COMPONENTS if r["crop"] == crop and r["region"] == region]
    assert rows, (crop, region)

    def ratio(name, base):
        return INDEX[(name, year)] / INDEX[(name, int(base))]

    def weight(r):
        return float(r["amount_usd"]) * (float(r["study_yield_tons_per_acre"]) if r["basis"] == "per_ton" else 1)

    indexed = [r for r in rows if r["basis"] in ("per_acre", "per_ton") and r["index_name"] != "weighted_inputs"]
    weighted = (sum(weight(r) * ratio(r["index_name"], r["base_year"]) for r in indexed)
                / sum(weight(r) for r in indexed))
    scale = lambda r: weighted if r["index_name"] == "weighted_inputs" else ratio(r["index_name"], r["base_year"])
    inputs = sum(float(r["amount_usd"]) * scale(r) for r in rows if r["basis"] == "per_acre") * acres
    harvest = sum(float(r["amount_usd"]) * scale(r) for r in rows if r["basis"] == "per_ton") * tons
    system = sum(float(r["amount_usd"]) for r in rows if r["basis"] == "per_acre_system"
                 and r["component"] == f"irrigation_system_{irrigation}") * weighted * acres
    water = surface_af * surface_price + ground_af * pump_cost(year)
    return inputs + harvest + system + water


def money_seasons(req, weather, ctx=None):
    ctx = ctx or make_context()
    bt = sim.run_backtest(req, weather)
    bt.context = ctx
    sim.apply_money(bt, ctx)
    return bt


@pytest.mark.parametrize("mode", ["current", "historical"])
def test_cost_matches_the_formula(weather, mode):
    # make_context's cost region (San Joaquin Valley North) has no almond study, so the
    # nearest region with one (Sacramento Valley) supplies the components.
    req = request([block(crop="almonds", acres=40, irrigation="micro_sprinkler", start=1, end=12)])
    req = req.model_copy(update={"price_mode": mode})
    bt = money_seasons(req, weather)
    for y, s in bt.seasons["b1"].items():
        m = s.money
        year = LATEST if mode == "current" else y
        assert m["year_used"] == year
        want = expected_cost("almonds", "Sacramento Valley", 40, m["tons"], "micro_sprinkler",
                             m["sw_af"], m["gw_af"], year)
        assert s.cost == pytest.approx(want, abs=2)
        assert m["cost"].harvest > 0 and m["cost"].irrigation_system > 0


def test_current_mode_costs_change_only_with_weather(weather):
    bt = money_seasons(request([block(crop="almonds", acres=40, irrigation="micro_sprinkler", start=1, end=12)]),
                       weather)
    seasons = list(bt.seasons["b1"].values())
    per_acre = {s.money["cost"].inputs_per_acre for s in seasons}
    systems = {s.money["cost"].irrigation_system for s in seasons}
    assert len(per_acre) == 1 and len(systems) == 1  # same input prices every year


def test_historical_mode_scales_costs_by_year(weather):
    req = request([block(crop="almonds", acres=40, irrigation="micro_sprinkler", start=1, end=12)], years=(2001, 2004))
    bt = money_seasons(req.model_copy(update={"price_mode": "historical"}), weather)
    per_acre = [bt.seasons["b1"][y].money["cost"].inputs_per_acre for y in bt.years]
    assert len(set(per_acre)) == len(per_acre)  # indexes differ by year
    assert per_acre[0] < per_acre[-1] * 1.2


def test_historical_year_without_index_uses_nearest_and_says_so(weather):
    req = request([block(crop="corn", acres=10, irrigation="flood")], years=(2001, 2004))
    bt = money_seasons(req.model_copy(update={"price_mode": "historical"}), weather)
    assert all(bt.seasons["b1"][y].money["year_used"] == y for y in bt.years)
    idx = economics.load_cost_indexes()
    v = idx.get("diesel", 1980)
    assert v.year == 1994 and v.is_estimate and "nearest year (1994)" in v.estimate_reason


def test_revenue_and_profit(weather):
    resp = sim.simulate(request([block(crop="almonds", acres=40, start=1, end=12)]),
                        weather, make_context())
    y = resp.blocks[0].yearly[0]
    price = CROP_PRICES.get("almonds", y.year, "current")  # $ / LB
    assert y.revenue == pytest.approx(y.relative_yield / median(r.relative_yield for r in resp.blocks[0].yearly) * 2000 * 40 * price.value, abs=50)
    assert y.profit == pytest.approx(y.revenue - y.cost, abs=1)


def test_tons_yield_priced_per_ton(weather):
    resp = sim.simulate(request([block(crop="walnuts", acres=10, irrigation="flood", start=1, end=12)]),
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
    lb = sim.simulate(request([block(crop="walnuts", irrigation="flood", start=1, end=12)]), weather, ctx)
    tons = sim.simulate(request([block(crop="walnuts", irrigation="flood", start=1, end=12)]), weather, make_context())
    assert lb.blocks[0].yearly[0].revenue == pytest.approx(tons.blocks[0].yearly[0].revenue, abs=1)


def test_bushels_use_crop_test_weight(weather):
    resp = sim.simulate(request([block(crop="corn", acres=15, irrigation="flood")]), weather, make_context())
    y = resp.blocks[0].yearly[0]
    price = CROP_PRICES.get("corn", y.year, "current")  # $ / BU
    assert y.revenue == pytest.approx(y.relative_yield / median(r.relative_yield for r in resp.blocks[0].yearly) * 160 * 15 * price.value, abs=10)


def test_unpriced_irrigation_system_gives_a_message_not_a_zero_cost(weather):
    # Oats are costed from USDA ERS, which has no sprinkler system line: no data, not $0.
    resp = sim.simulate(request([block("b1", crop="almonds", acres=40, start=1, end=12),
                                 block("b2", crop="oats", acres=15, irrigation="sprinkler",
                                       start=11, end=4)]), weather, make_context())
    oats = resp.blocks[1]
    for y in oats.yearly:
        assert y.revenue is None and y.cost is None and y.profit is None
        assert y.relative_yield > 0 and y.crop_water_use_in > 0
    assert any("Block b2 (oats): No cost data for sprinkler irrigation on oats" in a
               and "Irrigation types with cost data: flood." in a for a in resp.assumptions)
    # Farm totals add up the blocks that have money and say which were left out.
    almonds = resp.blocks[0].yearly
    for t, a in zip(resp.farm_totals, almonds):
        assert t.profit == pytest.approx(a.profit, abs=1)
    assert any("left out: b2 (oats)" in a for a in resp.assumptions)
    assert any("ranked by farm profit" in a for a in resp.assumptions)


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
    resp = sim.simulate(request([block(irrigation="flood")]), weather, ctx)
    assert resp.location.county is None and resp.location.cost_region is None
    assert resp.blocks[0].yearly[0].profit is not None


def test_surface_water_share_changes_water_cost(weather):
    surface = money_seasons(request([block(acres=10, irrigation="flood")], surface_water_share=1.0), weather)
    s = surface.seasons["b1"][2001]
    assert s.money["groundwater"] == 0 and s.money["surface"] == pytest.approx(s.money["water"] * 50, abs=0.01)
    ground = money_seasons(request([block(acres=10, irrigation="flood")], surface_water_share=0.0), weather)
    g = ground.seasons["b1"][2001]
    assert g.money["surface"] == 0
    assert g.money["groundwater"] == pytest.approx(g.money["water"] * pump_cost(LATEST), abs=0.01)
    assert s.cost - s.money["surface"] == pytest.approx(g.cost - g.money["groundwater"], abs=1)


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
    ctx = make_context()  # oats are costed from USDA ERS rows in cost_components.csv
    table = CROP_PRICES
    last = max(y for y in range(1980, 2030)
               if _has(table, "oats", y))
    first = min(y for y in range(1980, 2030) if _has(table, "oats", y))
    req = request([block(crop="oats", irrigation="flood", start=11, end=4)], years=(2001, 2004))
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
    resp = sim.simulate(request([block(crop="corn", irrigation="flood")]), weather,
                        sim._fallback_location_context(37.3, -120.48))
    assert resp.blocks[0].yearly[0].profit is not None
    assert sim.FALLBACK_NOTE in resp.assumptions


def test_missing_production_cost_gives_null_money(weather):
    ctx = make_context()
    del ctx["production_costs"]["corn"]
    resp = sim.simulate(request([block(crop="corn", irrigation="flood")]), weather, ctx)
    assert all(y.profit is None for y in resp.blocks[0].yearly)
    assert any("b1 (corn) has no production cost" in a for a in resp.assumptions)


ERS_RAW = ROOT / "data/raw/ers/oats.csv"
ERS = ({(r["Year"], r["Item"].strip()): float(r["Value"])
        for r in csv.DictReader(ERS_RAW.open(encoding="utf-8-sig"))
        if r["Region"] == "U.S. total" and r["Category"] == "Operating costs"} if ERS_RAW.exists() else {})


@pytest.mark.skipif(not ERS, reason="data/raw/ers/oats.csv not downloaded (data/raw is gitignored)")
def test_oats_cost_is_the_ers_operating_cost(weather):
    """Current mode: the latest ERS year; historical mode: each year's own ERS value, no
    index scaling (the nearest ERS year before 2005, flagged)."""
    req = request([block(crop="oats", acres=10, irrigation="flood", start=11, end=4)], years=(2004, 2005))
    cur = money_seasons(req, weather)
    for s in cur.seasons["b1"].values():
        c = s.money["cost"]
        assert c.inputs_per_acre == pytest.approx(ERS[(str(LATEST), "Total, operating costs")], abs=0.01)
        assert c.irrigation_system == 0 and c.system.component.source.startswith("USDA ERS")
        assert all(ln.component.is_estimate and ln.ratio == 1 for ln in c.lines)
    hist = money_seasons(req.model_copy(update={"price_mode": "historical"}), weather)
    for y, s in hist.seasons["b1"].items():
        c = s.money["cost"]
        ers_year = max(y, 2005)
        assert c.inputs_per_acre == pytest.approx(ERS[(str(ers_year), "Total, operating costs")], abs=0.01)
        if y < 2005:
            assert any("no ERS value for 2004, the nearest year (2005) is used" in e for e in c.estimates)
