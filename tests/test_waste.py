from types import SimpleNamespace

import numpy as np
import pytest

from backend import simulate as sim
from backend import waste
from conftest import make_context
from test_simulate import block, request


def flags_of(resp, kind):
    return [f for f in resp.waste_flags if f.type == kind]


def test_flood_flag_estimate(weather):
    resp = sim.simulate(request([block("b3", crop="corn", acres=15, irrigation="flood")]),
                        weather, make_context())
    (flag,) = flags_of(resp, "irrigation_method")
    applied = np.mean([y.water_applied_af for y in resp.blocks[0].yearly])
    assert flag.block_id == "b3"
    assert flag.estimated_af_per_year == pytest.approx(applied * (1 - 0.60 / 0.90), abs=0.2)
    assert "Flood irrigation on corn" in flag.message
    assert flag.estimated_cost_per_year > 0


def test_drip_has_no_method_flag(weather):
    resp = sim.simulate(request([block(irrigation="drip")]), weather, make_context())
    assert flags_of(resp, "irrigation_method") == []


def test_over_applied_fires_only_when_well_above_need(weather):
    base = sim.simulate(request([block(acres=20)]), weather, make_context())
    need = np.mean([t.water_applied_af for t in base.farm_totals])
    high = sim.simulate(request([block(acres=20)], water_applied_af=need * 1.5),
                        weather, make_context())
    (flag,) = flags_of(high, "over_applied")
    assert flag.block_id == "farm"
    assert flag.estimated_af_per_year == pytest.approx(need * 0.5, rel=0.02)
    close = sim.simulate(request([block(acres=20)], water_applied_af=need * 1.02),
                         weather, make_context())
    assert flags_of(close, "over_applied") == []


def test_sand_flag_only_for_high_water_crops_on_sand(weather):
    loam = sim.simulate(request([block(crop="almonds", start=1, end=12)]),
                        weather, make_context())
    assert flags_of(loam, "low_holding_soil") == []
    sand = sim.simulate(request([block("b1", crop="almonds", start=1, end=12),
                                 block("b2", crop="oats", start=11, end=4)], soil="sand"),
                        weather, make_context())
    flagged = {f.block_id for f in flags_of(sand, "low_holding_soil")}
    assert flagged == {"b1"}  # oats use far less than 30 inches


def test_rain_covered_counts_irrigation_in_rainy_weeks():
    # Two weeks: week 1 irrigated and rain beat ETc; week 2 irrigated, no rain.
    n = 14
    etc = np.full(n, 2.0)
    rain = np.zeros(n)
    rain[:7] = 3.0
    irr = np.zeros(n)
    irr[2] = 30.48   # 0.1 ft on 10 acres = 1 af net
    irr[9] = 30.48
    bal = SimpleNamespace(etc=etc, rain_in=rain, irrigation_net=irr)
    season = SimpleNamespace(balance=bal, acres=10, efficiency=0.5)
    bt = SimpleNamespace(
        years=[2001],
        request=SimpleNamespace(blocks=[SimpleNamespace(id="b1", crop="corn")]),
        seasons={"b1": {2001: season}},
        water_cost_per_af={2001: 60.0},
    )
    (flag,) = waste.rain_covered_flags(bt)
    assert flag.estimated_af_per_year == pytest.approx(2.0)   # 1 af net / 0.5 efficiency
    assert flag.estimated_cost_per_year == 120
    assert "Block b1 (corn)" in flag.message


def test_flags_sorted_largest_first(weather):
    resp = sim.simulate(request([block("b1", crop="almonds", acres=40, irrigation="sprinkler",
                                       start=1, end=12),
                                 block("b3", crop="corn", acres=15, irrigation="flood")],
                                soil="sand", water_applied_af=900), weather, make_context())
    afs = [f.estimated_af_per_year for f in resp.waste_flags]
    assert len(afs) >= 3
    assert afs == sorted(afs, reverse=True)


def test_no_water_price_gives_null_flag_cost(weather):
    resp = sim.simulate(request([block(irrigation="flood")]), weather,
                        make_context(surface_water_price_per_af=None))
    (flag,) = flags_of(resp, "irrigation_method")
    assert flag.estimated_cost_per_year is None
