import datetime as dt

import numpy as np
import pytest

from backend import simulate as sim
from backend.schemas import BlockIn, SimulateRequest, SimulateResponse
from conftest import make_weather


def request(blocks, years=(2001, 2004), **optional):
    return SimulateRequest.model_validate({
        "location": {"lat": 37.30, "lon": -120.48, "label": "Test farm"},
        "years": list(years),
        "blocks": blocks,
        "optional": optional,
    })


def block(id="b1", crop="corn", acres=10, irrigation="drip", start=5, end=9):
    return {"id": id, "crop": crop, "acres": acres, "irrigation": irrigation,
            "start_month": start, "end_month": end}


# ---------------------------------------------------------------- Kc curve

def test_kc_curve_shape():
    kc = {"ini": 0.3, "mid": 1.2, "end": 0.4}
    curve = sim.kc_curve(kc, [10, 20, 30, 15])
    assert len(curve) == 75
    assert np.all(curve[:10] == 0.3)                   # flat initial
    dev = curve[10:30]
    assert np.all(np.diff(dev) > 0)                    # linear rise
    assert dev[-1] == pytest.approx(1.2)
    assert np.allclose(np.diff(dev), np.diff(dev)[0])  # constant slope
    assert np.all(curve[30:60] == 1.2)                 # flat mid
    late = curve[60:]
    assert np.all(np.diff(late) < 0)                   # linear decline
    assert late[-1] == pytest.approx(0.4)


def test_stages_stretch_to_season_length():
    stages = {"ini": 30, "dev": 40, "mid": 50, "late": 30}
    for n in (100, 150, 153, 181, 365):
        scaled = sim.scale_stages(stages, n)
        assert sum(scaled) == n
    assert sim.scale_stages(stages, 300) == [60, 80, 100, 60]


def test_perennial_year_round_uses_own_season():
    params = {"kc": {"ini": 0.4, "mid": 0.9, "end": 0.65},
              "stage_days": {"ini": 30, "dev": 50, "mid": 130, "late": 30},
              "season_start_month": 3}
    b = BlockIn(id="b1", crop="almonds", acres=1, irrigation="drip", start_month=1, end_month=12)
    kc, active = sim.season_kc(params, "almonds", b, dt.date(2001, 1, 1), 365)
    march_1 = (dt.date(2001, 3, 1) - dt.date(2001, 1, 1)).days
    assert not active[:march_1].any()
    assert active[march_1: march_1 + 240].all()
    assert not active[march_1 + 240:].any()
    assert kc.max() == pytest.approx(0.9)
    assert np.all(kc[~active] == 0.4)                  # dormant Kc


# ---------------------------------------------------------------- months and seasons

def test_month_wrap_season_dates():
    b = BlockIn(id="b2", crop="oats", acres=1, irrigation="drip", start_month=11, end_month=4)
    start, end = sim.season_dates(b, 2002)
    assert start == dt.date(2001, 11, 1)
    assert end == dt.date(2002, 4, 30)


def test_non_wrap_season_dates():
    b = BlockIn(id="b3", crop="corn", acres=1, irrigation="drip", start_month=5, end_month=9)
    assert sim.season_dates(b, 2002) == (dt.date(2002, 5, 1), dt.date(2002, 9, 30))


def test_wrap_season_runs_and_is_reported_under_end_year(weather):
    resp = sim.simulate(request([block(crop="oats", start=11, end=4)]), weather)
    assert [y.year for y in resp.blocks[0].yearly] == [2001, 2002, 2003, 2004]


def test_missing_weather_raises():
    wx = make_weather(start="2001-01-01", end="2004-12-31")
    with pytest.raises(sim.WeatherUnavailableError, match="2000-11-01"):
        sim.simulate(request([block(crop="oats", start=11, end=4)]), wx)


# ---------------------------------------------------------------- water and yield

def test_effective_rain_threshold():
    pe = sim.effective_rain_mm(np.array([0.0, 4.9, 5.0, 20.0]))
    assert pe.tolist() == pytest.approx([0.0, 0.0, 4.0, 16.0])


def test_full_water_meets_crop_need(weather):
    resp = sim.simulate(request([block()]), weather)
    for y in resp.blocks[0].yearly:
        assert y.irrigation_need_af > 0
        # Full irrigation keeps depletion near RAW, so only heat can cut yield.
        assert y.relative_yield > 0.85


def test_flood_uses_more_water_than_drip_for_same_crop(weather):
    resp = sim.simulate(request([block("d", irrigation="drip"),
                                 block("f", irrigation="flood")]), weather)
    drip, flood = resp.blocks
    for d, f in zip(drip.yearly, flood.yearly):
        assert d.irrigation_need_af == pytest.approx(f.irrigation_need_af)  # same net need
        assert f.water_applied_af > d.water_applied_af
        assert f.water_applied_af / d.water_applied_af == pytest.approx(0.90 / 0.60, rel=0.02)


def test_water_cap_lowers_yield_and_caps_water(weather):
    full = sim.simulate(request([block(acres=40)]), weather)
    avg_applied = np.mean([y.water_applied_af for y in full.blocks[0].yearly])
    cap = 0.5 * avg_applied
    short = sim.simulate(request([block(acres=40)], water_available_af=cap), weather)
    for f, s, t in zip(full.blocks[0].yearly, short.blocks[0].yearly, short.farm_totals):
        assert s.relative_yield < f.relative_yield
        assert t.water_applied_af <= cap + 0.1
        assert s.irrigation_need_af == pytest.approx(f.irrigation_need_af)  # need is unchanged


def test_water_cap_split_in_proportion_to_need(weather):
    blocks = [block("big", acres=30), block("small", acres=10)]
    full = sim.simulate(request(blocks), weather)
    cap = 0.6 * full.farm_totals[0].water_applied_af
    short = sim.simulate(request(blocks, water_available_af=cap), weather)
    big, small = (b.yearly[0].water_applied_af for b in short.blocks)
    assert big / small == pytest.approx(3.0, rel=0.05)


def test_generous_cap_changes_nothing(weather):
    full = sim.simulate(request([block()]), weather)
    loose = sim.simulate(request([block()], water_available_af=1e6), weather)
    assert [y.water_applied_af for y in full.blocks[0].yearly] == \
           [y.water_applied_af for y in loose.blocks[0].yearly]


def test_relative_yield_ky_formula():
    # Ky 1.25 and ETa/ETc 0.8: 1 - 1.25 x 0.2 = 0.75
    assert sim.relative_yield(1.25, 80, 100, 0) == pytest.approx(0.75)
    assert sim.relative_yield(1.25, 100, 100, 8) == pytest.approx(1 - 8 * 0.0025)
    assert sim.relative_yield(1.25, 100, 100, 1000) == pytest.approx(0.90)  # heat cap
    assert sim.relative_yield(2.0, 0, 100, 0) == 0.0


def test_heat_stress_lowers_yield():
    # Normal summers peak near the corn threshold; 2002 is 5 C hotter.
    wx = make_weather(tmax_peak=35.5)
    hot = wx.index.year == 2002
    wx.loc[hot, "tmax_c"] += 5
    wx.loc[hot, "tmin_c"] += 5
    resp = sim.simulate(request([block()]), wx)
    by_year = {y.year: y for y in resp.blocks[0].yearly}
    normal, hot_year = by_year[2001], by_year[2002]
    assert hot_year.heat_stress_days > normal.heat_stress_days
    assert hot_year.relative_yield < normal.relative_yield
    assert hot_year.gdd > normal.gdd


def test_normal_heat_alone_does_not_cut_yield():
    # Every summer is equally hot, so no year is hotter than normal.
    resp = sim.simulate(request([block()]), make_weather(tmax_peak=42))
    for y in resp.blocks[0].yearly:
        assert y.heat_stress_days > 0
        assert y.relative_yield == pytest.approx(1.0, abs=0.01)


def test_rain_reduces_irrigation_need():
    dry = sim.simulate(request([block(crop="oats", start=11, end=4)]),
                       make_weather(winter_rain_mm=0))
    wet = sim.simulate(request([block(crop="oats", start=11, end=4)]),
                       make_weather(winter_rain_mm=15))
    d, w = dry.blocks[0].yearly[0], wet.blocks[0].yearly[0]
    assert d.effective_rain_in == 0
    assert w.effective_rain_in > 0
    assert w.irrigation_need_af < d.irrigation_need_af


def test_sand_needs_more_frequent_irrigation(weather):
    loam = sim.run_backtest(request([block()], soil="loam"), weather)
    sand = sim.run_backtest(request([block()], soil="sand"), weather)
    events = lambda bt: int((bt.seasons["b1"][2002].balance.irrigation_net > 0).sum())
    assert events(sand) > events(loam)


def test_water_balance_closes(weather):
    bt = sim.run_backtest(request([block(crop="almonds", start=1, end=12)]), weather)
    s = bt.seasons["b1"][2003]
    b = s.balance
    # Start at field capacity: final depletion = ETa - stored rain - irrigation.
    assert b.depletion[-1] == pytest.approx(b.eta.sum() - b.rain_eff.sum() - b.irrigation_net.sum())


# ---------------------------------------------------------------- response shape

def test_response_matches_contract(weather):
    blocks = [block("b1", "almonds", 40, "drip", 1, 12),
              block("b2", "oats", 15, "sprinkler", 11, 4),
              block("b3", "corn", 15, "flood", 5, 9)]
    resp = sim.simulate(request(blocks), weather)
    SimulateResponse.model_validate(resp.model_dump())
    assert resp.years == [2001, 2002, 2003, 2004]
    assert resp.location.grid_cell == (37.5, -120.625)
    assert len(resp.farm_totals) == 4
    t = resp.farm_totals[0]
    assert t.water_applied_af == pytest.approx(
        sum(b.yearly[0].water_applied_af for b in resp.blocks), abs=0.2)
    assert resp.summary.drought_years == []
    assert any("FAO-33" in a for a in resp.assumptions)
    assert any("ranked by" in a for a in resp.assumptions)


def test_micro_sprinkler_maps_to_reference_key(weather):
    resp = sim.simulate(request([block(irrigation="micro_sprinkler")]), weather)
    assert resp.blocks[0].yearly[0].water_applied_af > 0


def test_drought_years_in_range():
    wx = make_weather(start="2013-01-01", end="2016-12-31")
    resp = sim.simulate(request([block()], years=(2013, 2016)), wx)
    assert resp.summary.drought_years == [2014, 2015]
