"""Calculation records behind every information button (backend/calculations.py).

For every record in /api/simulate, /api/compare and /api/optimize responses:
  * each step's expr re-evaluates to the result printed at the end of its text,
  * the last step's result equals the record value,
  * the value equals the number the response (and so the UI) shows,
  * every input names a source, and every input that is not farmer, NASA or NASS data
    is tagged as an estimate with a reason or says why it is not an estimate,
  * sources are written for a farmer: no code files, publisher https links (never
    github.com), and every estimate lists what it was derived from.
"""

import re

import pytest

from backend import calculations, compare, optimize as opt, regions, simulate as engine
from backend.schemas import CompareRequest, OptimizeRequest, SimulateRequest
from conftest import make_context, make_weather
from hand_calculator import hand_check
from test_wording import advice_in

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


CODE_WORDS = re.compile(r"\.py\b|backend/|function|YieldGenerator model", re.IGNORECASE)


def assert_link(url, where):
    """Every link is a publisher's https page, never the code repository."""
    assert url.startswith("https://"), (where, url)
    assert "github.com" not in url, (where, url)


def check_sources(rid, rec):
    """Farmer-readable sources: no code files, publisher links, derived_from on estimates."""
    for i in rec["inputs"]:
        where = (rid, i["name"])
        assert str(i["source"]).strip(), where
        assert not CODE_WORDS.search(i["source"]), (where, i["source"])
        assert not any(CODE_WORDS.search(d) for d in i["derived_from"]), (where, i["derived_from"])
        assert isinstance(i["source_verified"], bool), where
        for link in i["links"]:
            assert_link(link["url"], where)
            assert link["label"].strip(), where
        if i["source_url"] is not None:
            assert_link(i["source_url"], where)
            assert i["source_url"] == i["links"][0]["url"], where
        if i["is_estimate"]:
            assert i["derived_from"] and all(d.strip() for d in i["derived_from"]), where
            assert i["links"], where


def check_record(rid, rec):
    assert rec["id"] == rid.removesuffix(" (lb)")
    check_sources(rid, rec)
    if "lb" in rec:
        check_sources(rid + " (lb)", rec["lb"])
    hand_check(rid, rec)
    if "lb" in rec:
        hand_check(rid + " (lb)", rec["lb"])
    for i in rec["inputs"]:
        assert str(i["source"]).strip(), (rid, i)
        if i["is_estimate"]:
            assert i["estimate_reason"], (rid, i)
        elif i["kind"] not in REPORTED:
            assert i["not_estimate_reason"], (rid, i)
    texts = [rec["label"], rec["formula_text"], rec["rounding"]] + [s["text"] for s in rec["steps"]]
    assert not any("\u2014" in t or "\u2013" in t for t in texts), rid
    assert not advice_in(texts + [i["source"] for i in rec["inputs"]]), rid
    assert not any("—" in i["source"] or "–" in i["source"] for i in rec["inputs"]), rid


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
    by_year = {t.year: t.profit for t in out.farm_totals}
    assert c["summary.best_year"]["value"] == by_year[out.summary.best_year]
    assert c["summary.worst_year"]["value"] == by_year[out.summary.worst_year]
    assert c["summary.worst_profit"]["value"] == min(t.profit for t in out.farm_totals if t.profit is not None)
    assert c["summary.avg_revenue"]["value"] == round(
        out.calculation_details["reconciliation"]["avg_revenue"])
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
                    assert c[f"{key}.{field}"]["lb"]["value"] == round(getattr(w, field) * 2000)


def test_audit_sources_link_to_publishers_not_code(simulated):
    _, out = simulated
    d = out.calculation_details
    assert "model_source" not in d
    links = [d["harvest_source"]]
    for b in d["blocks"]:
        links += b["sources"]
        for y in b["yearly"]:
            links += [v for v in y.values() if isinstance(v, dict) and "url" in v]
    for s in links:
        assert not CODE_WORDS.search(s["label"]), s["label"]
        if s["url"] is not None:
            assert_link(s["url"], s["label"])
    with pytest.raises(AssertionError):
        assert_link("https://github.com/x/y/blob/main/data.csv", "github")
    with pytest.raises(AssertionError):
        check_sources("x", {"inputs": [{"name": "x", "source": "YieldGenerator model, backend/simulate.py",
                                         "links": [], "derived_from": [], "source_verified": True,
                                         "source_url": None, "is_estimate": False}]})


def test_sources_name_the_real_data_used():
    """Grid cell, county, years, table and page come from the run's own data."""
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    c = out.calculations
    profit = {i["name"]: i for i in c["block.c.2003.profit"]["inputs"]}
    base = profit["Corn baseline yield (NASS median)"]
    assert base["source"].startswith("USDA NASS Quick Stats, Merced County corn grain yield, ")
    assert re.search(r"\d{4} to \d{4} median \(\d+ years\)", base["source"])
    assert base["links"][0]["url"] == "https://quickstats.nass.usda.gov"
    cost = next(i for n, i in profit.items() if n.startswith("Machinery and fuel per acre, UC Davis"))
    assert re.match(r"UC Davis Cost and Return Study, Corn, .+, \d{4}, p\. \d+: machinery fuel\.", cost["source"])
    assert cost["source_url"].startswith("https://coststudyfiles.ucdavis.edu/")
    diesel = next(i for n, i in profit.items() if n.startswith("EIA diesel price, "))
    assert diesel["source_url"].startswith("https://www.eia.gov/dnav/pet/")
    fert = next(i for n, i in profit.items() if n.startswith("NASS fertilizer index, "))
    assert fert["source"].startswith("USDA NASS Prices Paid Index (2011=100)")
    assert fert["source_url"] == "https://quickstats.nass.usda.gov"
    elec = next(i for n, i in profit.items() if n.startswith("Electricity price"))
    assert elec["source"].startswith("U.S. EIA, California commercial electricity price, ")
    assert elec["source_url"].startswith("https://www.eia.gov/opendata/browser/")
    water = profit["Surface water price"]
    assert water["source"].startswith("Merced Irrigation District 2024 rate")
    lift = profit["Well lift"]
    assert lift["source"].startswith("Default assumption: 150 ft well lift. Not measured. Replace with your own value.")
    etc = next(i for i in c["block.c.2003.crop_water_use_in"]["inputs"] if i["is_estimate"])
    assert "grid cell 37.5, -120.625" in etc["source"] and "FAO-56 Penman-Monteith" in etc["source"]
    assert "Table 12, p. 10" in etc["source"]
    assert {link["url"] for link in etc["links"]} >= {"https://power.larc.nasa.gov",
                                                     "https://www.fao.org/3/x0490e/x0490e00.htm"}
    assert "NASA POWER weather" in etc["derived_from"]
    ry = next(i for i in c["block.c.2003.relative_yield"]["inputs"] if i["is_estimate"])
    assert "Ky = " in ry["source"] and "FAO-66, Table 1, printed p. 7" in ry["source"]


def test_unverified_sources_are_flagged_not_guessed():
    req, ctx = CASES["merced_reference"]
    c = engine.simulate(req, wx=WX, context=ctx).calculations
    profit = {i["name"]: i for i in c["block.a.2003.profit"]["inputs"]}
    study = [i for n, i in profit.items() if ", UC Davis " in n and " study" in n]
    assert study and all(i["source_verified"] for i in study)  # study file, page and URL known
    assert not profit["Pump efficiency"]["source_verified"]  # defaults.json has no source for it
    eff = next(i for i in c["block.a.2003.water_applied_af"]["inputs"] if i["name"].startswith("Irrigation efficiency"))
    assert not eff["source_verified"] and "to be checked" in eff["source"]
    ry = next(i for i in c["block.a.2003.relative_yield"]["inputs"] if i["is_estimate"])
    assert not ry["source_verified"] and "source not yet verified" in ry["source"]  # almond Ky is a placeholder
    # Injected test context: the baseline matches no NASS records, so it is not claimed.
    test_ctx = engine.simulate(farm(), wx=WX, context=make_context()).calculations
    base = next(i for i in test_ctx["block.a.2003.profit"]["inputs"] if "baseline" in i["name"])
    assert not base["source_verified"] and base["source"].startswith("Source not yet verified")


def test_reported_and_estimated_inputs_are_tagged():
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    profit = out.calculations["block.a.2003.profit"]
    by_name = {i["name"]: i for i in profit["inputs"]}
    assert by_name["Almonds area"]["kind"] == "farmer" and not by_name["Almonds area"]["is_estimate"]
    assert by_name["Well lift"]["is_estimate"] and by_name["Well lift"]["estimate_reason"] == "Team assumption"
    assert by_name["Surface water share"]["is_estimate"]  # not entered, schema default
    cost = next(i for n, i in by_name.items() if n.startswith("Labor per acre, UC Davis"))
    assert cost["is_estimate"] and "UC Davis Cost and Return Study" in cost["source"]
    assert "file name" not in cost["estimate_reason"]
    assert cost["estimate_reason"].startswith(
        "Typical practice amounts from the UC Davis cost study, not this farm's actual records")
    # Almonds SV study has micro-sprinklers only: the drip system comes from the SJV South study.
    borrowed = next(i for n, i in by_name.items()
                    if n.endswith(": installed cost per acre, UC Davis San Joaquin Valley South 2024 study"))
    assert borrowed["value"] == 1800 and "prices no drip system" in borrowed["estimate_reason"]
    life = next(i for n, i in by_name.items() if n.endswith(": system life, UC Davis San Joaquin Valley South 2024 study"))
    assert life["value"] == 23 and life["unit"] == "years"
    price = next(i for i in profit["inputs"] if i["name"].startswith("Almonds price"))
    assert price["kind"] == "nass" and "USDA NASS Quick Stats" in price["source"]
    water = out.calculations["block.a.2003.crop_water_use_in"]
    etc = next(i for i in water["inputs"] if i["name"].startswith("Season crop water use"))
    assert etc["source"].startswith("Calculated from NASA POWER daily weather")
    assert "grid cell 37.5, -120.625" in etc["source"]
    assert etc["source_url"] == "https://power.larc.nasa.gov"
    assert "FAO-56" in etc["estimate_reason"]
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


def test_steps_show_both_the_exact_and_the_rounded_result():
    rec = calculations.Record("x", "x", "", 2, "x", "Rounded to 0.01.")
    one = rec.inp("One", 1, "", "test", kind="constant", why_not="test")
    three = rec.inp("Three", 3, "", "test", kind="constant", why_not="test")
    third = rec.step("{0} / {1}", [one, three], "{0}/{1}")
    rec.step("{0} x {1}", [third, three], "{0}*{1}", round_to=2)
    assert rec.steps[0]["text"] == "1 / 3 = 0.333333"
    assert rec.steps[1]["text"] == "0.333333 x 3 = 0.999999, rounded to 1.00"
    hand_check("x", rec.out(1.0))


# ---------------------------------------------------------------- cost records (inputs + harvest + water + system)

UCD_REASON = "Typical practice amounts from the UC Davis cost study, not this farm's actual records"
INPUT_KEYS = {"name", "value", "unit", "source", "source_url", "is_estimate", "estimate_reason"}
CODE_URL = re.compile(r"github\.com|gitlab\.com|\.(py|js|jsx|ts)(\?|#|$)|\b[0-9a-f]{40}\b")


def test_cost_record_shows_the_four_parts_with_numbers():
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    found = 0
    for b in out.blocks:
        for y in b.yearly:
            if y.cost is None:
                assert f"block.{b.id}.{y.year}.cost" not in out.calculations
                continue
            rec = out.calculations[f"block.{b.id}.{y.year}.cost"]
            found += 1
            assert rec["value"] == y.cost and rec["formula_text"] == "Cost = inputs + harvest + water + irrigation system"
            assert [p["name"] for p in rec["parts"]] == ["Inputs", "Harvest", "Water", "Irrigation system"]
            assert round(sum(p["value"] for p in rec["parts"])) == rec["value"]
            texts = [s["text"] for s in rec["steps"]]
            for label in ("Inputs cost: ", "Harvest cost: ", "Water cost (", "Irrigation system cost"):
                assert any(t.startswith(label) for t in texts), (rec["id"], label)
            assert texts[-1].startswith("Cost: inputs $") and " + harvest $" in texts[-1] \
                and " + water $" in texts[-1] and " + irrigation system $" in texts[-1]
            hand_check(rec["id"], rec)
            # The margin box shows the same four parts and the same cost.
            margin = out.calculations[f"block.{b.id}.{y.year}.profit"]
            assert margin["parts"] == rec["parts"]
    assert found


def test_cost_record_inputs_name_their_sources():
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    rec = out.calculations["block.a.2003.cost"]  # almonds, drip, Merced
    for i in rec["inputs"]:
        assert INPUT_KEYS <= set(i), i["name"]
    by = {i["name"]: i for i in rec["inputs"]}
    components = [i for n, i in by.items() if ", UC Davis " in n and " study" in n]
    assert components
    for i in components:
        assert i["source"].startswith("UC Davis Cost and Return Study, Almonds, ")
        assert i["source_url"].startswith("https://coststudyfiles.ucdavis.edu/")
        assert i["is_estimate"] and i["estimate_reason"].startswith(UCD_REASON)
    nass = [i for n, i in by.items() if n.startswith("NASS ")]
    assert nass and all(i["source"].startswith("USDA NASS Prices Paid Index (2011=100)")
                        and i["source_url"] == "https://quickstats.nass.usda.gov" for i in nass)
    diesel = next(i for n, i in by.items() if n.startswith("EIA diesel price, "))
    elec = next(i for n, i in by.items() if n.startswith("Electricity price, "))
    assert diesel["source"].startswith("U.S. EIA") and diesel["source_url"].startswith(
        "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=EMD_EPD2D_PTE_NUS_DPG")
    assert elec["source"].startswith("U.S. EIA") and elec["source_url"].startswith("https://www.eia.gov/")
    for name in ("Water applied (to 0.0001 acre-ft)", "Almonds harvest this season"):
        assert by[name]["source"] == "YieldGenerator simulation using NASA POWER weather"
        assert by[name]["source_url"] == "https://power.larc.nasa.gov"
    assert "Merced Irrigation District" in by["Surface water price"]["source"]
    assert by["Surface water price"]["source_url"] == "https://www.mercedid.org"
    assert by["Well lift"]["is_estimate"] and by["Well lift"]["estimate_reason"] == "Team assumption"


def test_no_source_url_points_to_code_or_a_commit():
    req, ctx = CASES["merced_reference"]
    out = engine.simulate(req, wx=WX, context=ctx)
    urls = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("source_url", "url") and isinstance(v, str):
                    urls.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(out.calculations)
    walk(out.calculation_details)
    assert urls
    bad = sorted({u for u in urls if CODE_URL.search(u) or not u.startswith("https://")})
    assert not bad, bad

def test_source_year_is_not_replaced_by_modeled_season():
    from backend.sources import Src
    record = calculations.Record("block.a.2021.cost", "Cost", "$", 0, "", "")
    record.inp("Electricity", 0.26, "$/kWh", Src("EIA", year=2025))
    record.inp("Water", 100, "acre-ft", Src("NASA"),kind="model",estimate="Water balance")
    record.inp("Pump efficiency", 0.6, "fraction", Src("Assumption", verified=False))
    assert [i["source_year"] for i in record.inputs] == [2025,2021,None]
    assert record.inputs[-1]["source_verified"] is False


def test_reference_year_metadata_matches_the_actual_input():
    from backend import sources
    assert sources.median_relative_yield("corn",[2001,2002,2003]).fields()["source_year"] == "2001 to 2003"
    ctx = regions.build_context({"state":"CA","county":"Merced","in_california":True})
    assert sources.cost_study("almonds",ctx).fields()["source_year"] == 2024
    assert sources.water_price(ctx).fields()["source_year"] == 2024
