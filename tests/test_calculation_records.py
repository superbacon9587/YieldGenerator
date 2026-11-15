"""Calculation records behind every information button (backend/calculations.py).

For every record in /api/simulate, /api/compare and /api/optimize responses:
  * each step's expr re-evaluates to the result printed at the end of its text,
  * the last step's result equals the record value,
  * the value equals the number the response (and so the UI) shows,
  * every input names a source, and every input that is not farmer, NASA or NASS data
    is tagged as an estimate with a reason or says why it is not an estimate.
"""

import re
from statistics import mean

import pytest

from backend import calculations, compare, optimize as opt, regions, simulate as engine
from backend.schemas import CompareRequest, OptimizeRequest, SimulateRequest
from conftest import make_context, make_weather
from test_wording import ADVICE

WX = make_weather()
REPORTED = {"farmer", "nasa", "nass"}
BLOCKS = [
    {"id": "a", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12},
    {"id": "c", "crop": "corn", "acres": 30.5, "irrigation": "flood", "start_month": 4, "end_month": 9},
    {"id": "o", "crop": "oats", "acres": 15, "irrigation": "sprinkler", "start_month": 11, "end_month": 4},
]


def farm(mode="current", **optional):
    return SimulateRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48}, "years": [2000, 2005], "price_mode": mode,
        "blocks": BLOCKS, "optional": optional})


CASES = {
    "current": (farm(), make_context()),
    "historical": (farm("historical"), make_context()),
    "water_cap_budget": (farm(water_available_af=120, budget_usd=150000, surface_water_share=0.3, soil="sand"),
                         make_context()),
    "all_groundwater": (farm(surface_water_share=0), make_context()),
    "merced_reference": (farm(), regions.build_context({"state": "CA", "county": "Merced", "in_california": True})),
    "fresno_reference": (farm(), regions.build_context({"state": "CA", "county": "Fresno", "in_california": True})),
}


@pytest.fixture(scope="module", params=list(CASES))
def simulated(request):
    req, ctx = CASES[request.param]
    return req, engine.simulate(req, wx=WX, context=ctx)


def printed_result(text):
    tail = text.rsplit(" = ", 1)[1].split(" ")[0]
    number = tail.replace("$", "").replace(",", "")
    decimals = len(number.split(".")[1]) if "." in number else 0
    return float(number), decimals


def check_record(rid, rec):
    assert rec["id"] == rid
    assert rec["steps"], rid
    for step in rec["steps"]:
        value = calculations.evaluate(step["expr"])
        if " = " in step["text"]:
            shown, decimals = printed_result(step["text"])
            assert shown == pytest.approx(step["result"], abs=1e-9), (rid, step)
            assert round(value, decimals) == pytest.approx(step["result"], abs=1e-9), (rid, step)
        else:
            assert value == step["result"], (rid, step)
    assert rec["steps"][-1]["result"] == pytest.approx(rec["value"], abs=1e-9), rid
    for i in rec["inputs"]:
        assert str(i["source"]).strip(), (rid, i)
        if i["is_estimate"]:
            assert i["estimate_reason"], (rid, i)
        elif i["kind"] not in REPORTED:
            assert i["not_estimate_reason"], (rid, i)
    assert rec["is_estimate"] == any(i["is_estimate"] for i in rec["inputs"])
    texts = [rec["label"], rec["formula_text"]] + [s["text"] for s in rec["steps"]] + [
        str(i[k]) for i in rec["inputs"] for k in ("name", "source", "estimate_reason", "not_estimate_reason")]
    assert not any("—" in t or "–" in t for t in texts), rid
    assert not [t for t in texts if ADVICE.search(t)], rid


def test_every_record_reevaluates_to_its_value(simulated):
    _, out = simulated
    assert len(out.calculations) > 100
    for rid, rec in out.calculations.items():
        check_record(rid, rec)


def test_values_match_the_numbers_the_response_shows(simulated):
    req, out = simulated
    c, s = out.calculations, out.summary_stats
    assert c["summary.avg_profit"]["value"] == s.avg_profit
    assert c["summary.avg_cost"]["value"] == s.avg_cost
    assert c["summary.total_profit"]["value"] == s.total_profit
    assert c["summary.avg_water_applied_af"]["value"] == s.avg_water_applied_af
    assert c["summary.avg_relative_yield"]["value"] == round(s.avg_relative_yield * 100, 1)
    assert c["summary.avg_yield_tons"]["value"] == s.avg_yield_tons
    assert c["summary.best_year"]["value"] == out.summary.best_year
    assert c["summary.worst_year"]["value"] == out.summary.worst_year
    assert c["summary.worst_profit"]["value"] == min(t.profit for t in out.farm_totals if t.profit is not None)
    assert c["summary.avg_revenue"]["value"] == pytest.approx(
        out.calculation_details["reconciliation"]["avg_revenue"], abs=0.005)
    if req.optional.budget_usd is not None:
        assert c["summary.years_over_budget"]["value"] == len(out.budget.years_over_budget)
    weights = {w.block_id: w for w in out.yield_weight}
    for b in out.blocks:
        for r in b.yearly:
            key = f"block.{b.id}.{r.year}"
            for field in ("crop_water_use_in", "effective_rain_in", "water_applied_af", "heat_stress_days", "gdd"):
                assert c[f"{key}.{field}"]["value"] == getattr(r, field), (key, field)
            assert c[f"{key}.relative_yield"]["value"] == round(r.relative_yield * 100, 1)
            if r.profit is None:
                assert f"{key}.profit" not in c
            else:
                assert c[f"{key}.profit"]["value"] == r.profit
            w = next(x for x in weights[b.id].yearly if x.year == r.year)
            for field in ("tons_per_acre", "tons"):
                if getattr(w, field) is None:
                    assert f"{key}.{field}" not in c
                else:
                    assert c[f"{key}.{field}"]["value"] == getattr(w, field)


def test_data_table_average_rows_match_the_table_rows(simulated):
    _, out = simulated
    c = out.calculations
    for scope in ["farm"] + [b.id for b in out.blocks]:
        for per_acre in (False, True):
            basis = "per_acre" if per_acre else "total"
            series = calculations.table_series(out, scope, per_acre)
            avgs = {}
            for metric, rows in series.items():
                values = [t / dv for _, t, dv in rows if t is not None and dv]
                rid = f"table.{scope}.{basis}.{metric}"
                if not values:
                    assert rid not in c
                    continue
                avgs[metric] = mean(values)
                assert c[rid]["value"] == pytest.approx(mean(values), abs=10 ** -c[rid]["decimals"]), rid
            if avgs.get("sales") and "margin" in avgs:
                rid = f"table.{scope}.{basis}.margin_pct"
                assert c[rid]["value"] == pytest.approx(100 * avgs["margin"] / avgs["sales"], abs=0.01)
    # Farm totals in the table are the same numbers as the summary cards.
    assert c["table.farm.total.harvest"]["value"] == pytest.approx(out.summary_stats.avg_yield_tons, abs=0.006)
    assert c["table.farm.total.water"]["value"] == pytest.approx(out.summary_stats.avg_water_applied_af, abs=0.06)


def test_reported_and_estimated_inputs_are_tagged():
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    profit = out.calculations["block.a.2003.profit"]
    by_name = {i["name"]: i for i in profit["inputs"]}
    assert by_name["Almonds area"]["kind"] == "farmer" and not by_name["Almonds area"]["is_estimate"]
    assert by_name["Well lift"]["estimate_reason"] == "Default assumption, 150 ft well lift"
    assert by_name["Surface water share"]["is_estimate"]  # not entered, schema default
    cost = by_name["Production cost excluding water"]
    assert cost["is_estimate"] and "UC Davis cost study" in cost["source"]
    assert "file name" in cost["estimate_reason"]  # 2024 study cited from a 2022 file
    price = next(i for i in profit["inputs"] if i["name"].startswith("Almonds price"))
    assert price["kind"] == "nass" and "USDA NASS Quick Stats" in price["source"]
    water = out.calculations["block.a.2003.crop_water_use_in"]
    et0 = next(i for i in water["inputs"] if i["name"].startswith("Reference ET0"))
    assert et0["source"].startswith("NASA POWER daily, grid cell 37.5, -120.625")
    assert et0["source_url"].startswith("https://power.larc.nasa.gov/")
    assert "FAO-56" in et0["estimate_reason"]
    assert profit["is_estimate"]
    entered = engine.simulate(farm(surface_water_share=0.5), wx=WX, context=ctx).calculations
    share = next(i for i in entered["block.a.2003.profit"]["inputs"] if i["name"] == "Surface water share")
    assert share["kind"] == "farmer" and not share["is_estimate"]


def test_compare_returns_records_for_the_ranking_table():
    a = farm(budget_usd=100000).model_dump()
    b = {**a, "blocks": [BLOCKS[0]], "available_acres": 40}
    req = CompareRequest.model_validate({"configs": [{"name": "A", "farm": a}, {"name": "B", "farm": b}]})
    import backend.simulate as sim
    original = sim.load_weather
    sim.load_weather = lambda lat, lon: WX
    try:
        res = compare.compare(req)
    finally:
        sim.load_weather = original
    for r in res.results:
        c = r.calculations
        for key in ("total_profit", "avg_profit", "avg_water_applied_af"):
            assert c[f"summary.{key}"]["value"] == getattr(r.summary_stats, key)
        assert c["summary.avg_relative_yield"]["value"] == round(r.summary_stats.avg_relative_yield * 100, 1)
        assert c["summary.years_over_budget"]["value"] == len(r.budget.years_over_budget)
        for rid, rec in c.items():
            check_record(rid, rec)


def test_optimize_returns_records_for_plan_numbers():
    req = OptimizeRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48}, "years": [2001, 2004], "available_acres": 100,
        "budget_usd": 400000, "allowed_crops": ["corn", "processing_tomatoes", "almonds"],
        "current_farm": {"blocks": BLOCKS[:2]}})
    res = opt.optimize(req, wx=WX, context=make_context(production_costs={
        **make_context()["production_costs"],
        "processing_tomatoes": {"cost_excl_water": 2500.0, "unit": "$ / ACRE", "region": "x", "source": "test"}},
        baseline_yields={**make_context()["baseline_yields"],
                         "processing_tomatoes": {"value": 45.0, "unit": "TONS / ACRE", "basis": "county",
                                                 "source": "test"}}))
    assert res.status in ("optimal", "feasible"), res
    parts = [res.plan, res.current_farm] + list(res.alternatives)
    for part in parts:
        c = part.calculations
        for key in ("avg_profit", "avg_yield_tons", "avg_water_applied_af", "avg_cost"):
            assert c[f"summary.{key}"]["value"] == getattr(part.summary_stats, key)
        for b in part.blocks:
            if b.avg_profit is not None:
                assert c[f"block.{b.id}.avg_profit"]["value"] == b.avg_profit
            if b.avg_yield_tons is not None:
                assert c[f"block.{b.id}.avg_yield_tons"]["value"] == b.avg_yield_tons
        for rid, rec in c.items():
            check_record(rid, rec)
    for key in ("avg_profit", "avg_yield_tons", "avg_water_applied_af", "avg_cost"):
        assert res.calculations[f"difference.{key}"]["value"] == getattr(res.difference_vs_current, key)
    for rid, rec in res.calculations.items():
        check_record(rid, rec)


def test_number_display_reproduces_rounding():
    rec = calculations.Record("x", "x", "", 2, "x")
    third = rec.step("{0} / 3", [calculations.N(1, 0)], "{0}/3", 4)
    rec.step("{0} x 3", [third], "{0}*3", 2)
    for step in rec.steps:
        shown, d = printed_result(step["text"])
        assert round(calculations.evaluate(step["expr"]), d) == shown
    assert re.search(r"0\.3333", rec.steps[1]["text"])
