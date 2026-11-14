"""Frost check for annual planting windows (backend/frost.py) and how the backtest and
the optimizer use it."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend import frost, optimize as opt, reference, simulate as engine
from backend.schemas import OptimizeRequest, SimulateRequest
from conftest import make_context, make_weather

MERCED_CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "power" / "37.5_-120.625.parquet"


def flat_weather(start="2000-01-01", end="2003-12-31", tmin=5.0):
    idx = pd.date_range(start, end, freq="D", name="date")
    return pd.DataFrame({"tmin_c": np.full(len(idx), tmin)}, index=idx)


# ---------------------------------------------------------------- the math

def test_frost_share_counts_years_with_frost_in_first_45_days():
    wx = flat_weather()
    wx.loc["2001-05-15", "tmin_c"] = -1.0    # Apr 1 is day 1, so May 15 is day 45: counts
    wx.loc["2002-05-16", "tmin_c"] = -5.0    # day 46: does not count
    wx.loc["2003-04-01", "tmin_c"] = 0.0     # planting day at exactly 0 C: counts
    wx.loc["2000-03-31", "tmin_c"] = -3.0    # the day before planting: does not count
    risk = frost.frost_risk(wx, 4, 8, [2000, 2001, 2002, 2003])
    assert (risk.frost_years, risk.years) == (2, 4)
    assert risk.share == 0.5
    assert risk.above_limit


def test_frost_share_wrapping_season_uses_the_previous_year():
    wx = flat_weather()
    wx.loc["2001-11-20", "tmin_c"] = -2.0    # oats planted Nov 2001 are the 2002 season
    risk = frost.frost_risk(wx, 11, 3, [2001, 2002, 2003])
    assert (risk.frost_years, risk.years) == (1, 3)
    assert risk.share == pytest.approx(1 / 3)


def test_frost_share_skips_years_outside_the_record_and_limit_is_strict():
    wx = flat_weather("2001-01-01", "2003-12-31")
    wx.loc["2002-03-10", "tmin_c"] = -1.0
    risk = frost.frost_risk(wx, 3, 7, [2000, 2001, 2002, 2003, 2004])  # 2000 and 2004 missing
    assert (risk.frost_years, risk.years) == (1, 3)
    wx.loc["2002-03-10":"2002-03-20", "tmin_c"] = np.nan                 # a gap is not counted
    assert frost.frost_risk(wx, 3, 7, [2001, 2002, 2003]).years == 2
    assert not frost.FrostRisk(1, 5).above_limit                         # 0.2 is not above 0.2
    assert frost.FrostRisk(2, 9).above_limit
    assert frost.FrostRisk(0, 0).share is None


# ---------------------------------------------------------------- backtest note

def test_backtest_notes_frost_as_a_neutral_fact():
    # Synthetic Merced shaped weather: every winter night in Dec goes below 0 C, and
    # summers are frost free.
    req = SimulateRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48}, "years": [2001, 2004],
        "blocks": [
            {"id": "oat", "crop": "oats", "acres": 10, "irrigation": "drip", "start_month": 12, "end_month": 4},
            {"id": "corn", "crop": "corn", "acres": 10, "irrigation": "drip", "start_month": 5, "end_month": 9},
            {"id": "alm", "crop": "almonds", "acres": 10, "irrigation": "drip", "start_month": 1, "end_month": 12},
        ]})
    resp = engine.simulate(req, wx=make_weather(), context=make_context(), include_comparisons=False)
    notes = [a for a in resp.assumptions if a.startswith("Frost occurred")]
    assert notes == ["Frost occurred within 45 days of planting in 4 of 4 years for block oat "
                     "(oats planted in Dec)."]


# ---------------------------------------------------------------- optimizer

def tomato_context():
    ctx = make_context()
    ctx["baseline_yields"]["processing_tomatoes"] = {"value": 50.0, "unit": "TONS / ACRE",
                                                     "basis": "county", "source": "test"}
    ctx["production_costs"]["processing_tomatoes"] = {"cost_excl_water": 2700.0, "unit": "$ / ACRE",
                                                      "region": "test", "source": "test"}
    ctx["production_costs"]["oats"] = {"cost_excl_water": 250.0, "unit": "$ / ACRE",
                                       "region": "test", "source": "test"}
    return ctx


def with_february_tomatoes(monkeypatch):
    entries = deepcopy(reference.crops())
    entries["processing_tomatoes"]["planting_months"]["value"] = [2, 3, 4, 5]
    monkeypatch.setattr(reference, "crops", lambda: entries)
    opt._CACHE.clear()


def optimize_request(**overrides):
    body = {"location": {"lat": 37.3, "lon": -120.48}, "years": [2001, 2004],
            "available_acres": 100, "budget_usd": 500_000}
    body.update(overrides)
    return OptimizeRequest.model_validate(body)


def test_february_tomatoes_excluded_and_winter_oats_kept(monkeypatch):
    with_february_tomatoes(monkeypatch)
    wx = make_weather()  # Merced shaped: February nights go below 0 C
    ctx = engine.LocationContext.model_validate(tomato_context()).model_dump()
    problem = opt.build_problem(optimize_request(), engine.prepare_weather(wx), ctx)
    starts = {(o.crop, o.key.start_month) for o in problem.options}
    assert ("processing_tomatoes", 2) not in starts
    assert {("processing_tomatoes", m) for m in (3, 4, 5)} <= starts
    assert problem.frost[("processing_tomatoes", 2)].share == 1.0
    oats_dec = [o for o in problem.options if o.key.crop == "oats" and o.key.start_month == 12]
    assert len(oats_dec) == 4 and all(o.frost_risk_share > 0.2 for o in oats_dec)  # tolerant: kept
    assert problem.frost_excluded == 4  # one window x 4 irrigation types
    note = next(e for e in problem.excluded if "frost occurred" in e)
    assert note.startswith("4 options were left out because frost occurred within 45 days")
    assert "processing tomato planted in Feb (4 of 4 years)" in note
    assert "oat" not in note
    for o in problem.options:
        assert (o.frost_risk_share is None) == (o.crop in engine.PERENNIALS)

    r = opt.optimize(optimize_request(), wx=wx, context=tomato_context())
    assert note in r.assumptions
    assert not any(b.crop == "processing_tomatoes" and b.start_month == 2 for b in r.plan.blocks)


def test_frost_sensitive_window_kept_when_frost_is_rare(monkeypatch):
    with_february_tomatoes(monkeypatch)
    wx = make_weather(tmax_peak=40.0)  # 6 C warmer: February stays above 0 C
    ctx = engine.LocationContext.model_validate(tomato_context()).model_dump()
    problem = opt.build_problem(optimize_request(), engine.prepare_weather(wx), ctx)
    assert problem.frost[("processing_tomatoes", 2)].share == 0.0
    assert any(o.crop == "processing_tomatoes" and o.key.start_month == 2 for o in problem.options)
    assert problem.frost_excluded == 0


@pytest.mark.skipif(not MERCED_CACHE.exists(), reason="cached Merced NASA POWER data not present")
def test_february_tomatoes_excluded_on_cached_merced_weather(monkeypatch):
    with_february_tomatoes(monkeypatch)
    raw = pd.read_parquet(MERCED_CACHE)
    years = list(range(2005, 2025))
    feb = frost.frost_risk(raw, 2, 6, years)
    assert feb.above_limit                       # 11 of 20 years when this test was written
    assert not frost.frost_risk(raw, 4, 8, years).above_limit
    assert frost.frost_risk(raw, 12, 4, years).above_limit   # winter oats: frequent, but tolerant
    wx = pd.DataFrame({"tmax_c": raw["tmax_c"], "tmin_c": raw["tmin_c"],
                       "precip_mm_day": raw["precip_mm_day"], "et0_mm_day": 4.0})
    ctx = engine.LocationContext.model_validate(tomato_context()).model_dump()
    problem = opt.build_problem(optimize_request(years=[2005, 2024]), engine.prepare_weather(wx), ctx)
    starts = {(o.crop, o.key.start_month) for o in problem.options}
    assert ("processing_tomatoes", 2) not in starts
    assert ("oats", 12) in starts
