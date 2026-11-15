"""How the cost responds to weather, acres, irrigation, location and price mode, and
where its sources point. Real data layer (backend/regions.py) and realistic inputs only."""

import csv
import re
from pathlib import Path

import pytest

from backend import economics, optimize as opt, regions, simulate as engine
from backend.schemas import OptimizeRequest, SimulateRequest
from conftest import make_weather, real_merced_weather

ROOT = Path(__file__).resolve().parent.parent
LOCATION = {"lat": 37.3, "lon": -120.48, "label": "Merced"}
MERCED = regions.build_context({"state": "CA", "county": "Merced", "in_california": True})
FRESNO = regions.build_context({"state": "CA", "county": "Fresno", "in_california": True})
INDEX = {(r["index_name"], int(r["year"])): float(r["value"])
         for r in csv.DictReader((ROOT / "data/prices/cost_indexes.csv").open())}
ERS_TOTAL = {int(r["Year"]): float(r["Value"])
             for r in csv.DictReader((ROOT / "data/raw/ers/oats.csv").open(encoding="utf-8-sig"))
             if r["Region"] == "U.S. total" and r["Item"].strip() == "Total, operating costs"}

TOMATOES = {"id": "t", "crop": "processing_tomatoes", "acres": 80, "irrigation": "drip", "start_month": 4, "end_month": 8}
ALMONDS = {"id": "a", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12}
OATS = {"id": "o", "crop": "oats", "acres": 12, "irrigation": "flood", "start_month": 11, "end_month": 4}


def costs(blocks, years, wx, ctx=MERCED, mode="current"):
    """{block id: {year: economics.BlockCost}} from the engine itself."""
    req = SimulateRequest.model_validate({"location": LOCATION, "years": list(years), "price_mode": mode,
                                          "blocks": blocks})
    bt = engine.run_backtest(req, wx)
    bt.context = engine.LocationContext.model_validate(ctx).model_dump()
    engine.apply_money(bt, bt.context)
    return {b["id"]: {y: bt.seasons[b["id"]][y].money["cost"] for y in bt.years} for b in blocks}


# ---------------------------------------------------------------- 2. weather

@pytest.mark.xfail(strict=True, reason=(
    "Model limitation, not a cost bug: each season starts with a full root zone (winter rain and "
    "pre-plant water are not counted) and the soil deficit left at harvest is not charged. On the real "
    "Merced weather, April-August 2014 had more reference ET (1,078 vs 1,031 mm) and less rain "
    "(36 vs 72 mm) than 2017, but 2014 ended with about 64 mm unrefilled versus 5 mm, so the model "
    "applies 282.0 acre-ft in 2014 and 287.5 in 2017. Flips to passing once the water model charges it."))
def test_drought_year_costs_more_water_than_wet_year_for_tomatoes_on_drip():
    c = costs([TOMATOES], (2014, 2017), real_merced_weather())["t"]
    assert c[2014].water > c[2017].water


def test_real_weather_fixture_has_the_drought_and_the_wet_year():
    wx = real_merced_weather()
    rain = {y: wx.loc[f"{y - 1}-10-01":f"{y}-09-30", "precip_mm_day"].sum() for y in (2014, 2017)}
    assert rain[2014] < 300 < 800 < rain[2017]  # water years: about 249 mm vs 827 mm


# ---------------------------------------------------------------- 3. acres, irrigation, location

def test_acres_irrigation_and_location_change_cost():
    wx = make_weather()
    years = (2002, 2003)
    base = costs([ALMONDS], years, wx)["a"]
    double = costs([{**ALMONDS, "acres": 80}], years, wx)["a"]
    micro = costs([{**ALMONDS, "irrigation": "micro_sprinkler"}], years, wx)["a"]
    fresno = costs([ALMONDS], years, wx, ctx=FRESNO)["a"]
    for y in years:
        assert double[y].total > base[y].total
        assert double[y].inputs == pytest.approx(2 * base[y].inputs, abs=0.02)
        assert micro[y].total != base[y].total
        assert micro[y].irrigation_system != base[y].irrigation_system
        assert micro[y].water != base[y].water  # micro-sprinklers apply more water than drip
        # Fresno (San Joaquin Valley South) pays a different surface water price for the same water.
        assert fresno[y].surface != base[y].surface and fresno[y].water != base[y].water
    assert FRESNO["surface_water_price_per_af"] != MERCED["surface_water_price_per_af"]


# ---------------------------------------------------------------- 4. price mode

def test_current_mode_input_costs_are_the_same_every_year():
    out = costs([TOMATOES, ALMONDS, OATS], (2001, 2004), make_weather())
    for block, by_year in out.items():
        assert len({c.inputs_per_acre for c in by_year.values()}) == 1, block
        assert len({c.irrigation_system for c in by_year.values()}) == 1, block
        assert {c.year_used for c in by_year.values()} == {max(y for _, y in INDEX)}, block


def test_historical_mode_follows_each_years_nass_index():
    out = costs([TOMATOES, ALMONDS], (2001, 2004), make_weather(), mode="historical")
    for block, by_year in out.items():
        assert len({c.inputs_per_acre for c in by_year.values()}) == 4, block
        for y, c in by_year.items():
            assert c.year_used == y
            for ln in c.lines:
                if ln.now is None:
                    continue
                k = ln.component
                want = round(INDEX[(k.index_name, y)] / INDEX[(k.index_name, k.base_year)], 6)
                assert ln.ratio == pytest.approx(want, abs=1e-9), (block, y, k.component)


def test_historical_oats_use_each_years_ers_value():
    out = costs([OATS], (2014, 2017), real_merced_weather(), mode="historical")["o"]
    for y, c in out.items():
        assert c.inputs_per_acre == pytest.approx(ERS_TOTAL[y], abs=0.01)
        assert all(ln.ratio == 1 and ln.component.base_year == y for ln in c.lines)
    assert len({c.inputs_per_acre for c in out.values()}) == 4


# ---------------------------------------------------------------- 5. source links

BAD_URL = re.compile(r"github\.com|gitlab\.com|localhost|127\.0\.0\.1|0\.0\.0\.0"
                     r"|\.(py|js|jsx|ts|tsx|ipynb|sh)(\?|#|$)|/blob/|\b[0-9a-f]{40}\b")


def all_urls(x, out):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("source_url", "url") and isinstance(v, str):
                out.append(v)
            all_urls(v, out)
    elif isinstance(x, list):
        for v in x:
            all_urls(v, out)
    return out


@pytest.mark.parametrize("mode", ["current", "historical"])
def test_every_source_url_is_a_public_https_page(mode):
    blocks = [ALMONDS, TOMATOES, OATS,
              {"id": "w", "crop": "walnuts", "acres": 25, "irrigation": "flood", "start_month": 1, "end_month": 12},
              {"id": "c", "crop": "corn", "acres": 15, "irrigation": "flood", "start_month": 5, "end_month": 9},
              {"id": "h", "crop": "alfalfa_hay", "acres": 30, "irrigation": "sprinkler", "start_month": 1, "end_month": 12}]
    req = SimulateRequest.model_validate({"location": LOCATION, "years": [2001, 2004], "price_mode": mode,
                                          "blocks": blocks})
    sim = engine.simulate(req, wx=make_weather(), context=MERCED)
    plan = opt.optimize(OptimizeRequest.model_validate({
        "location": LOCATION, "years": [2001, 2004], "price_mode": mode, "available_acres": 100,
        "budget_usd": 300_000, "allow_new_perennials": True}), wx=make_weather(), context=MERCED)
    records = list(sim.calculations.values()) + list(plan.calculations.values())
    assert any(r["id"].endswith(".cost") for r in records)
    urls = all_urls(records, []) + all_urls(sim.calculation_details, [])
    assert len(urls) > 100
    bad = sorted({u for u in urls if not u.startswith("https://") or BAD_URL.search(u)})
    assert not bad, bad


# ---------------------------------------------------------------- 7. optimizer

@pytest.mark.parametrize("objective", ["profit", "production_value", "profit_per_af"])
@pytest.mark.parametrize("mode", ["current", "historical"])
def test_optimizer_plan_matches_full_simulation_and_has_no_zero_system_cost(objective, mode):
    req = OptimizeRequest.model_validate({
        "location": LOCATION, "years": [2001, 2004], "price_mode": mode, "objective": objective,
        "available_acres": 100, "budget_usd": 300_000, "allow_new_perennials": True})
    wx = engine.prepare_weather(make_weather())
    ctx = engine.LocationContext.model_validate(MERCED).model_dump()
    problem = opt.build_problem(req, wx, ctx)
    sol = opt.solve(problem, objective)
    assert sol.status == "optimal"
    blocks = opt.plan_blocks(problem, sol.acres)
    resp = opt.run_engine(req, blocks, wx, ctx)
    predicted = opt.predicted_totals(problem, sol.acres)
    stats = resp.summary_stats
    assert stats.avg_profit == pytest.approx(predicted["profit"], rel=0.01)
    assert stats.avg_cost == pytest.approx(predicted["cost"], rel=0.01)
    assert stats.avg_water_applied_af == pytest.approx(predicted["water"], rel=0.01)
    assert opt.verify(problem, sol.acres, blocks, resp) == []
    # No option the optimizer could pick has a $0 irrigation system cost, except oats (USDA ERS).
    for o in problem.options:
        one = costs([{"id": "x", "crop": o.crop, "acres": 1.0, "irrigation": o.key.irrigation,
                      "start_month": o.key.start_month, "end_month": o.key.end_month}],
                    (2001, 2004), make_weather(), mode=mode)["x"]
        for c in one.values():
            if o.crop == "oats":
                assert c.irrigation_system == 0 and c.system.component.source.startswith("USDA ERS")
            else:
                assert c.irrigation_system > 0, o.key


# ---------------------------------------------------------------- water source (optional.surface_water_share)

DEFAULTS = economics.load_defaults()


def water_costs(share, years=(2001, 2004)):
    req = SimulateRequest.model_validate({"location": LOCATION, "years": list(years), "blocks": [TOMATOES],
                                          "optional": {"surface_water_share": share}})
    bt = engine.run_backtest(req, make_weather())
    bt.context = engine.LocationContext.model_validate(MERCED).model_dump()
    engine.apply_money(bt, bt.context)
    return {y: bt.seasons["t"][y].money for y in bt.years}


def pump_per_af(year):
    return DEFAULTS["well_lift_ft"] * 1.024 / DEFAULTS["pump_efficiency"] * INDEX[("electricity", year)]


def test_surface_water_only_is_acre_ft_times_district_price():
    assert MERCED["surface_water_price_per_af"] == 50  # Merced Irrigation District
    for m in water_costs(1.0).values():
        c = m["cost"]
        assert c.groundwater == 0 and m["gw_af"] == 0
        assert c.water == c.surface == pytest.approx(m["water"] * 50, abs=0.01)


def test_groundwater_only_is_the_pumping_cost_only():
    latest = max(y for _, y in INDEX)
    for m in water_costs(0.0).values():
        c = m["cost"]
        assert c.surface == 0 and m["sw_af"] == 0
        assert c.water == c.groundwater == pytest.approx(m["water"] * pump_per_af(latest), abs=0.01)


def test_half_and_half_is_the_average_of_surface_and_wells():
    surface, wells, mix = water_costs(1.0), water_costs(0.0), water_costs(0.5)
    for y in mix:
        assert mix[y]["water"] == surface[y]["water"] == wells[y]["water"]  # same acre-ft
        avg = (surface[y]["cost"].water + wells[y]["cost"].water) / 2
        assert mix[y]["cost"].water == pytest.approx(avg, abs=0.02)


@pytest.mark.parametrize("share", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_each_acre_ft_is_charged_once(share):
    surface, wells = water_costs(1.0), water_costs(0.0)
    for y, m in water_costs(share).items():
        assert m["sw_af"] + m["gw_af"] == pytest.approx(m["water"], abs=2e-4)  # split, never repeated
        full_both = surface[y]["cost"].water + wells[y]["cost"].water
        assert m["cost"].water <= max(surface[y]["cost"].water, wells[y]["cost"].water) + 0.01
        assert m["cost"].water < full_both


def test_cost_record_shows_the_share_and_only_the_water_parts_used():
    for share, kept, dropped in ((1.0, "Surface water price", "Well lift"),
                                 (0.0, "Well lift", "Surface water price")):
        req = SimulateRequest.model_validate({"location": LOCATION, "years": [2002, 2003], "blocks": [TOMATOES],
                                              "optional": {"surface_water_share": share}})
        rec = engine.simulate(req, wx=make_weather(), context=MERCED).calculations["block.t.2003.cost"]
        names = {i["name"]: i for i in rec["inputs"]}
        assert names["Surface water share"]["value"] == share and names["Surface water share"]["kind"] == "farmer"
        assert kept in names and dropped not in names
        water = next(s["text"] for s in rec["steps"] if s["text"].startswith("Water cost ("))
        assert water.startswith("Water cost (surface water only)" if share else "Water cost (wells only)")


def test_optimizer_prices_water_with_the_requested_share():
    wx = engine.prepare_weather(make_weather())
    ctx = engine.LocationContext.model_validate(MERCED).model_dump()
    body = {"location": LOCATION, "years": [2001, 2004], "available_acres": 100, "budget_usd": 300_000,
            "allowed_crops": ["processing_tomatoes"]}
    by_share = {}
    for share in (1.0, 0.0):
        req = OptimizeRequest.model_validate({**body, "surface_water_share": share})
        problem = opt.build_problem(req, wx, ctx)
        by_share[share] = {o.key: o.cost for o in problem.options}
        sol = opt.solve(problem, "profit")
        blocks = opt.plan_blocks(problem, sol.acres)
        resp = opt.run_engine(req, blocks, wx, ctx)
        assert resp.summary_stats.avg_cost == pytest.approx(opt.predicted_totals(problem, sol.acres)["cost"], rel=0.01)
        assert opt.verify(problem, sol.acres, blocks, resp) == []
    assert all((by_share[1.0][k] != by_share[0.0][k]).all() for k in by_share[1.0])
    assert OptimizeRequest.model_validate(body).surface_water_share == 0.5  # old requests still work
