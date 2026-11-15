"""Optimizer tests. Synthetic weather and a fixed location context keep them offline.

Optimality is checked two independent ways: by brute force over acre splits on a
tiny case, and against single-option farms run through simulate.simulate.
"""

import itertools
import re
import time
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import optimize as opt, reference, simulate as engine
from backend.api import app
from backend.schemas import OptimizeRequest, SimulateRequest
from conftest import make_context, make_weather

YEARS = (2001, 2004)
WX = make_weather()
LOCATION = {"lat": 37.3, "lon": -120.48}
ALMONDS_40 = {"blocks": [
    {"id": "a", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12}]}


def profitable_context():
    """Corn and oats both make money (the default test context has corn losing money
    and oats without a production cost)."""
    ctx = make_context()
    ctx["baseline_yields"]["corn"]["value"] = 300.0
    ctx["production_costs"]["oats"] = {"cost_excl_water": 250.0, "unit": "$ / ACRE",
                                       "region": "test", "source": "test"}
    return ctx


def request(**overrides):
    body = {"location": LOCATION, "years": list(YEARS), "available_acres": 100,
            "budget_usd": 200_000}
    body.update(overrides)
    return OptimizeRequest.model_validate(body)


def run(ctx=None, wx=None, **overrides):
    return opt.optimize(request(**overrides), wx=wx if wx is not None else WX,
                        context=ctx or profitable_context())


def clean_ctx(ctx):
    return engine.LocationContext.model_validate(ctx).model_dump()


def rerun(req, blocks, ctx, wx=WX):
    return opt.run_engine(req, blocks, engine.prepare_weather(wx), clean_ctx(ctx))


def varied_weather():
    """Hot and mild years alternate, so water use and cost change a lot by year."""
    parts = [make_weather(f"{y}-01-01", f"{y}-12-31", et0_peak=9.0 if y % 2 else 5.0)
             for y in range(1999, 2005)]
    wx = pd.concat(parts)
    wx.attrs = parts[0].attrs
    return wx


def single_block(ctx, crop, irrigation, start, end, acres=100.0):
    req = SimulateRequest.model_validate({
        "location": LOCATION, "years": list(YEARS),
        "blocks": [{"id": "b", "crop": crop, "acres": acres, "irrigation": irrigation,
                    "start_month": start, "end_month": end}]})
    return engine.simulate(req, wx=WX, context=ctx, include_comparisons=False)


def monthly_acres(blocks):
    acres = [0.0] * 12
    for b in blocks:
        for m in b.months:
            acres[m - 1] += b.acres
    return acres


# ---------------------------------------------------------------- options

def test_options_and_wrapping_windows():
    assert opt.season_months("corn") == 5  # 150 days
    assert opt.planting_windows("corn") == [(3, 7), (4, 8), (5, 9), (6, 10)]
    assert opt.planting_windows("oats") == [(1, 5), (10, 2), (11, 3), (12, 4)]  # wraps December
    assert opt.planting_windows("almonds") == [(1, 12)]
    for crop in ("processing_tomatoes", "corn", "oats"):
        n = opt.season_months(crop)
        assert abs(n * opt.DAYS_PER_MONTH - reference.season_days(crop)) <= opt.DAYS_PER_MONTH / 2
    r = run(allow_new_perennials=True)
    # 4 irrigation types x almonds and walnuts, 16 corn, 16 oats (tomatoes and alfalfa
    # have no money data in the test context).
    assert r.options_considered == 4 * 2 + 16 + 16


def test_per_acre_results_come_from_the_engine_and_are_cached(monkeypatch):
    ctx = clean_ctx(profitable_context())
    wx = engine.prepare_weather(WX)
    req = request()
    opt._CACHE.clear()
    problem = opt.build_problem(req, wx, ctx)
    corn = next(o for o in problem.options if o.key == opt.OptionKey("corn", "drip", 6, 10))
    one = single_block(ctx, "corn", "drip", 6, 10, acres=1.0)
    yearly = one.blocks[0].yearly
    assert corn.months == (6, 7, 8, 9, 10)
    np.testing.assert_allclose(corn.relative_yield, [y.relative_yield for y in yearly], atol=5e-4)
    np.testing.assert_allclose(corn.water, [y.water_applied_af for y in yearly], atol=0.05)
    np.testing.assert_allclose(corn.cost, [y.cost for y in yearly], atol=0.5)
    np.testing.assert_allclose(corn.tons, [y.tons_per_acre for y in one.yield_weight[0].yearly], atol=5e-4)
    calls = []
    real = engine.run_backtest
    monkeypatch.setattr(engine, "run_backtest", lambda *a, **k: calls.append(1) or real(*a, **k))
    opt.build_problem(req, wx, ctx)
    assert calls == []  # every option came from the cache


# ---------------------------------------------------------------- optimality

def tiny_case(monkeypatch, **overrides):
    """2 crops x 2 irrigation types x 2 start months = 8 options on 20 acres."""
    entries = deepcopy(reference.crops())
    entries["corn"]["planting_months"]["value"] = [4, 6]
    entries["oats"]["planting_months"]["value"] = [10, 11]
    monkeypatch.setattr(reference, "crops", lambda: entries)
    opt._CACHE.clear()
    body = dict(allowed_crops=["corn", "oats"], allowed_irrigation=["drip", "flood"],
                available_acres=20, max_share_per_crop=1, min_block_acres=5)
    body.update(overrides)
    req = request(**body)
    problem = opt.build_problem(req, engine.prepare_weather(WX), clean_ctx(profitable_context()))
    opt._CACHE.clear()
    return req, problem


def brute_force(problem, objective):
    """Best objective over every split in 5 acre steps that meets every limit."""
    req, opts = problem.request, problem.options
    steps = np.arange(0, req.available_acres + 1e-9, 5.0)
    grid = np.array(list(itertools.product(steps, repeat=len(opts))))
    ok = np.ones(len(grid), bool)
    for row in opt.constraint_rows(problem):
        activity = grid @ row.coeffs
        ok &= (activity >= row.lb - 1e-9) & (activity <= row.ub + 1e-9)
    means = opt.per_acre_means(problem)
    if objective == "profit_per_af":
        water = grid @ means["water"]
        values = np.where(water > 1e-9, (grid @ means["profit"]) / np.maximum(water, 1e-12), -np.inf)
    else:
        values = grid @ means[objective]
    feasible = values[ok]
    assert feasible.size > 1
    return feasible.max()


@pytest.mark.parametrize("objective, limits", [
    ("profit", {}),
    ("profit", {"budget_usd": 9_000}),
    ("profit", {"budget_usd": 15_000, "water_available_af": 30}),
    ("profit", {"budget_usd": 9_000, "budget_rule": "average"}),
    ("production_value", {"budget_usd": 12_000}),
    ("profit_per_af", {"budget_usd": 12_000}),
])
def test_milp_beats_or_matches_brute_force(monkeypatch, objective, limits):
    _, problem = tiny_case(monkeypatch, objective=objective, **limits)
    assert len(problem.options) == 8
    sol = opt.solve(problem, objective)
    assert sol.status == "optimal"
    best = brute_force(problem, objective)
    assert sol.objective_value >= best - 1e-6 * max(1.0, abs(best))


def test_profit_plan_is_best_single_corn_option():
    """Every corn window covers Jun and Jul, so with share 1 and a loose budget the best
    plan is all the land in the corn option with the highest profit per acre."""
    ctx = profitable_context()
    singles = {(irr, s, e): single_block(ctx, "corn", irr, s, e)
               for s, e in opt.planting_windows("corn")
               for irr in ("drip", "micro_sprinkler", "sprinkler", "flood")}
    best_key = max(singles, key=lambda k: singles[k].summary_stats.avg_profit)
    r = run(ctx, allowed_crops=["corn"], max_share_per_crop=1, budget_usd=10_000_000)
    assert [(b.irrigation, b.start_month, b.end_month, b.acres) for b in r.plan.blocks] == [(*best_key, 100.0)]
    assert r.plan.summary_stats == singles[best_key].summary_stats
    assert any(s.startswith("Land is fully used") for s in r.binding_constraints)


def test_profit_per_af_matches_best_single_option_ratio():
    """A mix never beats the best single option's profit per acre-foot (mediant rule)."""
    ctx = profitable_context()
    singles = {(irr, s, e): single_block(ctx, "corn", irr, s, e).summary_stats
               for s, e in opt.planting_windows("corn")
               for irr in ("drip", "micro_sprinkler", "sprinkler", "flood")}
    ratio = {k: s.avg_profit / s.avg_water_applied_af for k, s in singles.items()}
    best_key = max(ratio, key=ratio.get)
    r = run(ctx, objective="profit_per_af", allowed_crops=["corn"])
    (block,) = r.plan.blocks
    assert (block.irrigation, block.start_month, block.end_month) == best_key
    assert block.acres == 70.0  # the most profit at that ratio: the 70% share limit
    s = r.plan.summary_stats
    assert s.avg_profit / s.avg_water_applied_af == pytest.approx(ratio[best_key], rel=2e-3)


def test_profit_per_af_with_dry_farmed_option():
    # Synthetic winters are wet, so oats never need irrigation water.
    r = run(objective="profit_per_af")
    assert r.plan.summary_stats.avg_water_applied_af == 0
    assert {b.crop for b in r.plan.blocks} == {"oats"}
    assert opt.ZERO_WATER_NOTE in r.assumptions


def test_production_value_coefficients_use_current_prices(monkeypatch):
    """With price_mode historical, profit uses each year's price but production value
    uses the current price for every year, exactly as a current-mode run would."""
    ctx = clean_ctx(profitable_context())
    wx = engine.prepare_weather(WX)
    hist = opt.build_problem(request(price_mode="historical"), wx, ctx)
    now = opt.build_problem(request(price_mode="current"), wx, ctx)
    now_by_key = {o.key: o for o in now.options}
    assert any(not np.allclose(o.revenue, now_by_key[o.key].revenue) for o in hist.options)
    for o in hist.options:
        np.testing.assert_allclose(o.revenue_current, now_by_key[o.key].revenue)
    means = opt.per_acre_means(hist)
    np.testing.assert_allclose(means["production_value"], [o.revenue_current.mean() for o in hist.options])


def test_production_value_uses_current_prices_in_any_price_mode():
    common = dict(objective="production_value", max_share_per_crop=1, budget_usd=10_000_000)
    now = run(price_mode="current", **common)
    past = run(price_mode="historical", **common)
    key = lambda r: [(b.crop, b.start_month, b.acres) for b in r.plan.blocks]
    assert key(now) == key(past)
    assert any("current prices" in a for a in past.assumptions)
    assert past.plan.summary_stats.avg_yield_tons is not None


# ---------------------------------------------------------------- land

def test_winter_and_summer_annuals_share_acres():
    r = run(max_share_per_crop=1)
    by_crop = {}
    for b in r.plan.blocks:
        by_crop[b.crop] = by_crop.get(b.crop, 0) + b.acres
    assert by_crop == {"corn": 100.0, "oats": 100.0}
    assert max(monthly_acres(r.plan.blocks)) <= 100 + 1e-9
    assert r.plan.land.over_capacity_months == []
    assert any(s.startswith("Land is fully used") for s in r.binding_constraints)


def test_land_never_exceeded_in_any_month():
    for share in (0.4, 0.7, 1.0):
        r = run(allow_new_perennials=True, max_share_per_crop=share, budget_usd=10_000_000,
                available_acres=73.3)
        assert max(monthly_acres(r.plan.blocks)) <= 73.3 + 1e-9
        for crop in {b.crop for b in r.plan.blocks}:
            assert sum(b.acres for b in r.plan.blocks if b.crop == crop) <= share * 73.3 + 1e-9


# ---------------------------------------------------------------- budget and water

def test_every_year_budget_holds_and_average_can_go_over():
    ctx, wx = profitable_context(), varied_weather()
    common = dict(allowed_crops=["corn"], allowed_irrigation=["flood"], max_share_per_crop=1,
                  budget_usd=40_000)
    every = run(ctx, wx, **common)
    average = run(ctx, wx, budget_rule="average", **common)
    every_costs = [t.cost for t in rerun(request(**common), every.plan.blocks, ctx, wx).farm_totals]
    avg_costs = [t.cost for t in rerun(request(**common), average.plan.blocks, ctx, wx).farm_totals]
    assert max(every_costs) <= 40_000 and max(every_costs) > 39_000
    assert every.plan.budget.years_over_budget == []
    assert sum(avg_costs) / len(avg_costs) <= 40_000
    assert max(avg_costs) > 40_000                      # a single year goes over
    assert average.plan.budget.years_over_budget        # reported, and allowed by the rule
    assert average.plan.blocks[0].acres > every.plan.blocks[0].acres
    assert any(re.fullmatch(r"Budget is the limit in \d{4}( and \d{4})?\.", s)
               for s in every.binding_constraints)
    assert "Budget is the limit on average." in average.binding_constraints


def test_water_limit_holds_every_year():
    ctx, wx = profitable_context(), varied_weather()
    r = run(ctx, wx, water_available_af=90)
    totals = rerun(request(water_available_af=90), r.plan.blocks, ctx, wx).farm_totals
    assert all(t.water_applied_af <= 90 + 0.05 for t in totals)
    assert max(t.water_applied_af for t in totals) > 85      # the limit binds in a hot year
    assert any(s.startswith("Water limit is reached in") for s in r.binding_constraints)
    assert r.status == "optimal" and r.error_detail is None  # the engine never rationed


def test_min_block_reshapes_a_small_leftover_block():
    common = dict(budget_usd=17_100, max_share_per_crop=0.15)
    loose = run(min_block_acres=0, **common)
    assert min(b.acres for b in loose.plan.blocks) < 5
    strict = run(min_block_acres=5, **common)
    assert all(b.acres >= 5 for b in strict.plan.blocks)
    assert {b.crop for b in strict.plan.blocks} == {"corn", "oats"}
    corn_only = run(min_block_acres=5, allowed_crops=["corn"], **common)
    assert strict.plan.summary_stats.avg_profit > corn_only.plan.summary_stats.avg_profit


# ---------------------------------------------------------------- perennials

def test_perennials_locked_when_new_plantings_are_off():
    r = run(current_farm=ALMONDS_40, budget_usd=10_000_000, max_share_per_crop=1)
    assert sum(b.acres for b in r.plan.blocks if b.crop == "almonds") == 40
    assert not any(b.crop in ("walnuts", "alfalfa_hay") for b in r.plan.blocks)
    assert opt.PERENNIAL_LAG_NOTE in r.assumptions
    assert any("fixed at the current 40 acres" in s for s in r.binding_constraints)


def test_locked_perennial_can_change_irrigation():
    farm = {"blocks": [{**ALMONDS_40["blocks"][0], "irrigation": "flood"}]}
    r = run(current_farm=farm, budget_usd=10_000_000)
    almonds = [b for b in r.plan.blocks if b.crop == "almonds"]
    assert sum(b.acres for b in almonds) == 40
    assert {b.irrigation for b in almonds} != {"flood"}  # drip costs less water at the same yield


def test_locked_perennial_is_kept_even_when_it_loses_money():
    ctx = profitable_context()
    ctx["production_costs"]["almonds"]["cost_excl_water"] = 50_000.0
    r = run(ctx, current_farm=ALMONDS_40, budget_usd=10_000_000)
    assert sum(b.acres for b in r.plan.blocks if b.crop == "almonds") == 40


def test_new_perennials_allowed():
    r = run(allow_new_perennials=True, max_share_per_crop=1, budget_usd=10_000_000)
    assert any(b.crop == "almonds" for b in r.plan.blocks)
    assert opt.PERENNIAL_LAG_NOTE in r.assumptions


@pytest.mark.parametrize("overrides, phrase", [
    ({"budget_usd": 50_000}, "The locked almond acres cost more than the budget in 2001"),
    ({"available_acres": 30}, "more than the 30 available acres"),
    ({"max_share_per_crop": 0.3}, "more than the 30% crop share limit"),
    ({"water_available_af": 50}, "The locked almond acres need more water than the limit"),
    ({"allowed_crops": ["corn"]}, "almonds are not in the allowed crops"),
])
def test_locked_perennial_infeasible_reasons(overrides, phrase):
    r = run(current_farm=ALMONDS_40, **overrides)
    assert r.status == "infeasible" and r.plan is None
    assert phrase in r.infeasible_reason


# ---------------------------------------------------------------- verification

def test_simulate_rerun_matches_optimizer_within_one_percent():
    ctx = profitable_context()
    for overrides in ({}, {"budget_usd": 60_000, "water_available_af": 120},
                      {"current_farm": ALMONDS_40}):
        req = request(**overrides)
        problem = opt.build_problem(req, engine.prepare_weather(WX), clean_ctx(ctx))
        sol = opt.solve(problem, "profit")
        blocks = opt.plan_blocks(problem, sol.acres)
        resp = rerun(req, blocks, ctx)
        predicted = opt.predicted_totals(problem, sol.acres)
        stats = resp.summary_stats
        assert stats.avg_profit == pytest.approx(predicted["profit"], rel=0.01)
        assert stats.avg_cost == pytest.approx(predicted["cost"], rel=0.01)
        assert stats.avg_water_applied_af == pytest.approx(predicted["water"], rel=0.01)
        assert opt.verify(problem, sol.acres, blocks, resp) == []


def test_plan_reproduces_in_simulate_endpoint(monkeypatch):
    ctx = profitable_context()
    monkeypatch.setattr(engine, "load_weather", lambda lat, lon: WX)
    monkeypatch.setattr(engine, "get_location_context", lambda lat, lon: ctx)
    client = TestClient(app)
    body = {"location": LOCATION, "years": list(YEARS), "available_acres": 100,
            "budget_usd": 60_000}
    out = client.post("/api/optimize", json=body).json()
    blocks = [{k: v for k, v in b.items() if k not in ("avg_profit", "avg_yield_tons")}
              for b in out["plan"]["blocks"]]
    sim = client.post("/api/simulate", json={
        "location": LOCATION, "years": list(YEARS), "available_acres": 100,
        "blocks": blocks, "optional": {"budget_usd": 60_000}}).json()
    assert sim["summary_stats"] == out["plan"]["summary_stats"]
    assert sim["budget"] == out["plan"]["budget"]
    assert sim["land"] == out["plan"]["land"]


def test_verification_failure_returns_error_not_a_plan(monkeypatch):
    real = opt.evaluate_options

    def cheap_costs(*args):
        out = real(*args)
        return {k: (v if isinstance(v, str) else opt.replace(v, cost=v.cost * 0.5))
                for k, v in out.items()}  # the optimizer now disagrees with the engine

    monkeypatch.setattr(opt, "evaluate_options", cheap_costs)
    r = run(budget_usd=60_000)
    assert r.status == "error" and r.plan is None
    assert "differs from the optimizer" in r.error_detail


# ---------------------------------------------------------------- outputs

def test_block_averages_and_difference_vs_current():
    ctx = profitable_context()
    current = {"blocks": ALMONDS_40["blocks"] + [
        {"id": "c", "crop": "corn", "acres": 15, "irrigation": "flood", "start_month": 5, "end_month": 9}]}
    r = run(ctx, current_farm=current)
    for part in (r.plan, r.current_farm, *r.alternatives):
        assert all(b.avg_yield_tons is not None for b in part.blocks)
        assert sum(b.avg_profit for b in part.blocks) == pytest.approx(
            part.summary_stats.avg_profit, abs=len(part.blocks))
        assert sum(b.avg_yield_tons for b in part.blocks) == pytest.approx(
            part.summary_stats.avg_yield_tons, abs=0.05)
    req = request(current_farm=current)
    assert r.current_farm.summary_stats == rerun(req, req.current_farm.blocks, ctx).summary_stats
    p, c, d = r.plan.summary_stats, r.current_farm.summary_stats, r.difference_vs_current
    assert d.avg_profit == p.avg_profit - c.avg_profit
    assert d.avg_cost == p.avg_cost - c.avg_cost
    assert d.avg_water_applied_af == pytest.approx(p.avg_water_applied_af - c.avg_water_applied_af)
    assert d.avg_yield_tons == pytest.approx(p.avg_yield_tons - c.avg_yield_tons)


def test_alternatives_use_different_option_sets():
    r = run(objective="profit_per_af", allowed_crops=["corn"])
    assert 1 <= len(r.alternatives) <= 3
    assert [a.label for a in r.alternatives] == [f"Alternative {i + 1}" for i in range(len(r.alternatives))]
    sets = [frozenset((b.crop, b.irrigation, b.start_month) for b in r.plan.blocks)]
    sets += [frozenset((b.crop, b.irrigation, b.start_month) for b in a.blocks) for a in r.alternatives]
    assert len(sets) == len(set(sets))
    for a in r.alternatives:
        assert a.budget.years_over_budget == []


def test_no_advice_language():
    r = run(current_farm=ALMONDS_40, budget_usd=150_000)
    text = " ".join(r.binding_constraints + r.assumptions + [a.label for a in r.alternatives])
    for word in ("recommend", "should", "advis", "suggest", "consider", "best for"):
        assert word not in text.lower(), word
    assert "\u2014" not in text  # no em dashes


# ---------------------------------------------------------------- no plan

def test_impossible_budget_is_infeasible_with_reason():
    r = run(budget_usd=100)
    assert r.status == "infeasible" and r.plan is None and r.difference_vs_current is None
    assert "more than the $100 budget" in r.infeasible_reason


def test_min_block_larger_than_share_is_infeasible():
    r = run(available_acres=10, max_share_per_crop=0.4, min_block_acres=5)
    assert r.status == "infeasible" and "minimum block is larger" in r.infeasible_reason


def test_no_options_left_is_infeasible():
    r = run(allowed_crops=["walnuts"])
    assert r.status == "infeasible" and r.options_considered == 0
    assert "Walnuts was left out" in r.infeasible_reason


def test_no_profitable_plan():
    r = run(make_context(), allowed_crops=["corn"])  # corn loses money in the default context
    assert r.status == "no_profitable_plan" and r.plan is None
    assert "unplanted" in r.infeasible_reason


def test_missing_money_data_excludes_crop_with_note():
    r = run(make_context())
    assert any("Oats was left out" in a and "production cost" in a for a in r.assumptions)


# ---------------------------------------------------------------- API

def test_optimize_endpoint_shape_and_validation(monkeypatch):
    monkeypatch.setattr(engine, "load_weather", lambda lat, lon: WX)
    monkeypatch.setattr(engine, "get_location_context", lambda lat, lon: profitable_context())
    client = TestClient(app)
    body = {"location": LOCATION, "years": list(YEARS), "available_acres": 100,
            "budget_usd": 200_000, "current_farm": ALMONDS_40}
    resp = client.post("/api/optimize", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) == {"status", "objective", "plan", "current_farm", "difference_vs_current",
                         "alternatives", "binding_constraints", "infeasible_reason",
                         "error_detail", "options_considered", "assumptions"}
    assert set(data["plan"]) == {"blocks", "summary_stats", "budget", "land"}
    assert set(data["current_farm"]) == {"blocks", "summary_stats", "budget"}
    assert set(data["plan"]["blocks"][0]) == {"id", "crop", "acres", "irrigation", "start_month",
                                              "end_month", "avg_profit", "avg_yield_tons"}
    assert set(data["difference_vs_current"]) == {"avg_profit", "avg_yield_tons",
                                                  "avg_water_applied_af", "avg_cost"}
    assert all(isinstance(s, str) for s in data["binding_constraints"])
    for missing in ("available_acres", "budget_usd"):
        bad = {k: v for k, v in body.items() if k != missing}
        assert client.post("/api/optimize", json=bad).status_code == 422
    for field, value in (("objective", "tons"), ("budget_rule", "monthly"),
                         ("max_share_per_crop", 0), ("allowed_crops", []), ("extra", 1)):
        assert client.post("/api/optimize", json={**body, field: value}).status_code == 422


def test_optimize_endpoint_weather_error_is_422(monkeypatch):
    monkeypatch.setattr(engine, "load_weather", lambda lat, lon: make_weather("2003-01-01", "2004-12-31"))
    client = TestClient(app)
    body = {"location": LOCATION, "years": [2001, 2004], "available_acres": 100,
            "budget_usd": 200_000, "current_farm": ALMONDS_40}
    assert client.post("/api/optimize", json=body).status_code == 422


def test_runtime_twenty_years_every_crop():
    weather = make_weather("1999-01-01", "2019-12-31")
    opt._CACHE.clear()
    start = time.perf_counter()
    r = opt.optimize(request(years=[2000, 2019], allow_new_perennials=True, water_available_af=200),
                     wx=weather, context=profitable_context())
    elapsed = time.perf_counter() - start
    assert r.status == "optimal"
    assert elapsed < 15, f"Optimizer took {elapsed:.1f}s"
