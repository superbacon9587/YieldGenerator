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
            assert r["water_cost"] == pytest.approx(r["surface_water_cost"]+r["groundwater_cost"])
            assert r["sale_quantity"]*r["pounds_per_sale_unit"] == pytest.approx(r["harvest_tons"]*2000)
            assert r["revenue_unrounded"]-r["cost_unrounded"] == pytest.approx(r["profit_unrounded"])
            assert abs(r["displayed"]["revenue"]-r["revenue_unrounded"]) <= .5
            assert r["production_cost_excl_water"] == 3000*40
    rec = details["reconciliation"]
    assert rec["matched_avg_revenue"]-rec["matched_avg_cost"] == pytest.approx(rec["avg_profit"], abs=1)
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
    assert almond["verified_cost_study"]["cover_year"] == 2024
    assert almond["verified_cost_study"]["pdf_page"] == 19
    assert not any("has not been reconciled" in w for w in almond["source_warnings"])
    assert almond["production_cost_source"]["region"] == "Sacramento Valley"

def test_water_limit_reduces_absolute_harvest_and_sales_without_recalibration():
    req = request()
    req.blocks = [req.blocks[0]]
    wx,ctx=make_weather(),make_context()
    free=engine.simulate(req,wx=wx,context=ctx,include_comparisons=False)
    cap=req.model_copy(deep=True);cap.optional.water_available_af=20
    limited=engine.simulate(cap,wx=wx,context=ctx,include_comparisons=False)
    assert limited.yield_weight[0].reference_relative_yield == free.yield_weight[0].reference_relative_yield
    assert sum(r.tons for r in limited.yield_weight[0].yearly) < sum(r.tons for r in free.yield_weight[0].yearly)
    assert sum(r.revenue for r in limited.blocks[0].yearly) < sum(r.revenue for r in free.blocks[0].yearly)
    for row,harvest in zip(limited.blocks[0].yearly,limited.yield_weight[0].yearly):
        assert harvest.tons == pytest.approx(1.0*row.relative_yield/free.yield_weight[0].reference_relative_yield*40,abs=.01)


def test_verified_pdf_categories_reconcile_to_extracted_nonwater_cost():
    from backend.study_audit import studies
    for study in studies():
        assert sum(study['nonwater_categories_per_acre'].values()) == study['nonwater_cost_per_acre']
        assert study['operating_cost_per_acre']-study['water_cost_per_acre'] == study['nonwater_cost_per_acre']
        assert len(study['sha256']) == 64


def test_same_season_stays_stable_when_display_period_changes():
    wx, ctx = make_weather(), make_context()
    req = request()
    short = req.model_copy(update={"years": [2002, 2004]})
    a = engine.simulate(req, wx=wx, context=ctx, include_comparisons=False)
    b = engine.simulate(short, wx=wx, context=ctx, include_comparisons=False)
    for x,y in zip(a.blocks,b.blocks):
        assert next(row for row in x.yearly if row.year == 2003) == next(row for row in y.yearly if row.year == 2003)
    assert a.yield_weight[0].reference_relative_yield == b.yield_weight[0].reference_relative_yield


def test_sales_and_cost_coverage_are_independent():
    out = engine.simulate(request(), wx=make_weather(), context=make_context())
    assert out.financial_coverage["revenue"]["complete"]
    assert not out.financial_coverage["margin"]["complete"]
    for total, almond, oats in zip(out.farm_totals, out.blocks[0].yearly, out.blocks[1].yearly):
        assert total.revenue == pytest.approx(almond.revenue + oats.revenue, abs=1)
        assert oats.revenue > 0 and oats.cost is None and oats.profit is None
        assert total.profit == almond.profit
