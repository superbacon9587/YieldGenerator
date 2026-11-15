from statistics import mean
from urllib.parse import parse_qs, urlparse
import pytest
from backend import simulate as engine, economics
from backend.schemas import SimulateRequest
from conftest import make_context, make_weather


def request(mode="current"):
    return SimulateRequest.model_validate({"location":{"lat":37.3,"lon":-120.48}, "years":[2001,2004], "price_mode":mode, "blocks":[{"id":"a","crop":"almonds","acres":40,"irrigation":"drip","start_month":1,"end_month":12},{"id":"o","crop":"oats","acres":15,"irrigation":"sprinkler","start_month":11,"end_month":4}]})


@pytest.mark.parametrize("mode", ["current", "historical"])
def test_harvest_sales_cost_and_margin_share_the_same_quantity(mode):
    out = engine.simulate(request(mode), wx=make_weather(), context=make_context())
    details = out.calculation_details
    assert details["excluded_financial_blocks"][0]["block_id"] == "o"
    for block in details["blocks"]:
        for r in block["yearly"]:
            assert r["harvest_tons"] == pytest.approx(r["harvest_tons_per_acre"] * block["acres"])
            if r["profit_unrounded"] is None:
                assert r["displayed"]["profit"] is None
                continue
            assert r["sale_quantity"]*r["crop_price"]["value"] == pytest.approx(r["revenue_unrounded"])
            assert r["cost_unrounded"] == pytest.approx(r["production_cost_excl_water"]+r["water_cost"])
            assert r["revenue_unrounded"]-r["cost_unrounded"] == pytest.approx(r["profit_unrounded"])
            assert abs(r["displayed"]["revenue"]-r["revenue_unrounded"]) <= .5
            assert r["production_cost_excl_water"] == 3000*40
    rec = details["reconciliation"]
    assert rec["avg_revenue"]-rec["avg_cost"] == pytest.approx(rec["avg_profit"], abs=1)
    assert rec["avg_profit"] == pytest.approx(mean(r.profit for r in out.farm_totals))


def test_year_specific_sources_and_wrapping_season():
    out = engine.simulate(request(), wx=make_weather(), context=make_context())
    oats = next(b for b in out.calculation_details["blocks"] if b["id"] == "o")
    r = oats["yearly"][0]
    assert r["season_start"] == "2000-11-01"
    assert r["season_end"] == "2001-04-30"
    query = parse_qs(urlparse(r["weather_source"]["url"]).query)
    assert query["start"] == ["20001101"]
    assert query["end"] == ["20010430"]
    assert query["latitude"] == ["37.5"]
    assert "key" not in query
    assert r["crop_price"]["year"] != 2001  # latest reference price, not weather year
    assert all(int(record["year"]) == r["crop_price"]["year"] for record in r["price_source"]["records"])
    assert "not an expense input" in out.calculation_details["cost_basis"]


def test_temperature_water_and_rain_arithmetic_is_traceable():
    out = engine.simulate(request(), wx=make_weather(), context=make_context())
    for b in out.calculation_details["blocks"]:
        for r in b["yearly"]:
            assert r["net_irrigation_applied_mm"]/304.8*b["acres"]/r["irrigation_efficiency"] == pytest.approx(r["applied_water_unrounded_af"])
            assert r["displayed"]["crop_water_use_in"] == round(r["etc_all_mm"]/25.4, 1)
            assert r["displayed"]["effective_rain_in"] == round(r["effective_rain_mm"]/25.4, 1)
            water = 1-r["ky"]*(1-r["eta_active_mm"]/r["etc_active_mm"]) if r["etc_active_mm"] else 1
            assert round(min(max(water-r["heat_penalty_fraction"],0),1),3) == r["displayed"]["relative_yield"]

def test_conflicting_cost_source_year_is_flagged_not_claimed_verified():
    from backend import regions
    ctx = regions.build_context({"state":"CA", "county":"Merced", "in_california":True})
    out = engine.simulate(request(), wx=make_weather(), context=ctx)
    almond = out.calculation_details["blocks"][0]["yearly"][0]
    assert any("2024" in w and "2022" in w for w in almond["source_warnings"])
    assert almond["production_cost_source"]["region"] == "Sacramento Valley"
