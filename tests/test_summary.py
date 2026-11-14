import statistics

import pytest

from backend import simulate as sim
from backend import summary, units
from backend.schemas import SimulateRequest
from conftest import make_context
from test_simulate import block, request

FARM = [
    block("b1", crop="almonds", acres=40, irrigation="drip", start=1, end=12),
    block("b2", crop="oats", acres=15, irrigation="sprinkler", start=11, end=4),
    block("b3", crop="corn", acres=15, irrigation="flood", start=5, end=9),
]


def simulate(weather, blocks=FARM, ctx=None, available_acres=None, **optional):
    body = request(blocks, **optional).model_dump()
    if available_acres is not None:
        body["available_acres"] = available_acres
    req = SimulateRequest.model_validate(body)
    return req, sim.simulate(req, weather, ctx or make_context())


# ---------------------------------------------------------------- request

def test_available_acres_defaults_to_sum_of_blocks():
    req = request(FARM)
    assert req.available_acres == 70


def test_budget_defaults_to_none():
    assert request(FARM).optional.budget_usd is None


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        SimulateRequest.model_validate({**request(FARM).model_dump(), "available_acres": 0})
    body = request(FARM).model_dump()
    body["optional"]["budget_usd"] = -5
    with pytest.raises(ValueError):
        SimulateRequest.model_validate(body)


# ---------------------------------------------------------------- summary stats

def test_summary_stats_math(weather):
    _, resp = simulate(weather)
    s = resp.summary_stats
    totals = resp.farm_totals
    assert s.years_count == len(totals) == 4
    assert s.total_profit == pytest.approx(sum(t.profit for t in totals), abs=1)
    assert s.avg_profit == pytest.approx(s.total_profit / 4, abs=1)
    assert s.avg_cost == pytest.approx(sum(t.cost for t in totals) / 4, abs=1)
    assert s.avg_relative_yield == pytest.approx(
        sum(t.relative_yield for t in totals) / 4, abs=0.001)
    assert s.avg_water_applied_af == pytest.approx(
        sum(t.water_applied_af for t in totals) / 4, abs=0.1)


def test_summary_stats_null_without_money(weather):
    ctx = make_context(production_costs={})
    _, resp = simulate(weather, ctx=ctx)
    s = resp.summary_stats
    assert s.total_profit is None and s.avg_profit is None and s.avg_cost is None
    assert s.avg_relative_yield is not None and s.avg_water_applied_af is not None


def test_summary_stats_partial_years_noted():
    from backend.schemas import SimulateResponse
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent.parent / "docs" / "example_response.json").read_text())
    data["farm_totals"][0]["profit"] = None
    resp = SimulateResponse.model_validate(data)
    stats, notes = summary.summary_stats(resp)
    assert stats.years_count == 25
    assert stats.total_profit == pytest.approx(sum(t["profit"] for t in data["farm_totals"][1:]))
    assert notes == ["Profit totals and averages use the 24 of 25 years that have price data."]


# ---------------------------------------------------------------- budget

def test_no_budget(weather):
    _, resp = simulate(weather)
    assert resp.budget.budget_usd is None
    assert resp.budget.years_over_budget == []
    assert resp.budget.max_overrun_usd is None


def test_budget_years_and_overrun(weather):
    _, base = simulate(weather)
    costs = {t.year: t.cost for t in base.farm_totals}
    limit = sorted(costs.values())[1] + 1  # two years at or under, two over
    _, resp = simulate(weather, budget_usd=limit)
    over = [y for y, c in costs.items() if c > limit]
    assert resp.budget.budget_usd == limit
    assert resp.budget.years_over_budget == over
    assert len(over) == 2
    assert resp.budget.max_overrun_usd == pytest.approx(max(costs.values()) - limit, abs=1)


def test_generous_budget_never_over(weather):
    _, resp = simulate(weather, budget_usd=1e9)
    assert resp.budget.years_over_budget == []
    assert resp.budget.max_overrun_usd is None


def test_budget_partial_cost_noted(weather):
    _, resp = simulate(weather, budget_usd=1e9)  # oats have no production cost
    assert any("blocks with price data only" in a for a in resp.assumptions)


# ---------------------------------------------------------------- land

def test_winter_and_summer_blocks_share_acres():
    # Oats Nov to Apr and corn May to Sep on the same 15 acres: never overlap.
    req = SimulateRequest.model_validate({
        **request([FARM[1], FARM[2]]).model_dump(), "available_acres": 15})
    lnd, notes = summary.land(req)
    assert lnd.peak_acres_in_use == 15
    assert lnd.over_capacity_months == []
    assert notes == []
    assert summary.monthly_acres(req) == [15, 15, 15, 15, 15, 15, 15, 15, 15, 0, 15, 15]


def test_overlapping_blocks_over_capacity():
    # Oats Nov to Apr and corn Apr to Aug: April has both.
    corn = dict(FARM[2], start_month=4, end_month=8)
    req = SimulateRequest.model_validate({
        **request([FARM[1], corn]).model_dump(), "available_acres": 15})
    lnd, notes = summary.land(req)
    assert lnd.over_capacity_months == ["Apr"]
    assert lnd.peak_acres_in_use == 30
    assert lnd.peak_month == "Apr"
    assert "Apr" in notes[0] and "15.0 available acres" in notes[0]


def test_land_peak_month_and_note_in_response(weather):
    _, resp = simulate(weather, available_acres=50)
    assert resp.land.available_acres == 50
    assert resp.land.peak_acres_in_use == 55  # almonds 40 + oats or corn 15
    assert resp.land.peak_month == "Jan"
    assert resp.land.over_capacity_months == [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Nov", "Dec"]
    assert any("exceed the 50.0 available acres" in a for a in resp.assumptions)


# ---------------------------------------------------------------- yield weight (was production)

@pytest.mark.parametrize("unit,expected", [
    ("LB / ACRE", "lb / 2000"), ("TONS / ACRE", "already tons"), ("BU/ACRE", "bu x 56 lb / 2000"),
    ("bu / acre", "bu x 56 lb / 2000"),
])
def test_yield_weight_conversion_text(unit, expected):
    assert units.conversion_text(unit, "corn") == expected


def test_yield_weight_math(weather):
    _, resp = simulate(weather)
    weights = {w.block_id: w for w in resp.yield_weight}
    assert [w.block_id for w in resp.yield_weight] == ["b1", "b2", "b3"]
    almonds = resp.blocks[0].yearly
    assert weights["b1"].source_unit == "LB / ACRE"
    median_ry = statistics.median(y.relative_yield for y in almonds)
    for w, y in zip(weights["b1"].yearly, almonds):
        assert w.year == y.year
        assert w.relative_yield == y.relative_yield
        assert w.tons == pytest.approx(
            2000 / 2000 * y.relative_yield / median_ry * 40, abs=0.01)
    assert weights["b3"].source_unit == "BU / ACRE"
    corn = resp.blocks[2].yearly
    corn_median = statistics.median(y.relative_yield for y in corn)
    assert weights["b3"].yearly[0].tons == pytest.approx(
        160 * 56 / 2000 * corn[0].relative_yield / corn_median * 15, abs=0.01)


def test_summary_stats_avg_yield_tons(weather):
    _, resp = simulate(weather)
    per_year = [sum(w.yearly[i].tons for w in resp.yield_weight)
                for i in range(len(resp.years))]
    assert resp.summary_stats.avg_yield_tons == pytest.approx(
        sum(per_year) / len(per_year), abs=0.01)


def test_yield_weight_null_without_baseline(weather):
    _, resp = simulate(weather, blocks=[block("b4", crop="processing_tomatoes", start=4, end=8)])
    (w,) = resp.yield_weight
    assert w.source_unit is None
    assert all(y.tons is None and y.tons_per_acre is None for y in w.yearly)
    assert resp.summary_stats.avg_yield_tons is None
