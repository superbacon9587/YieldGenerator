"""Numbers that must agree, checked on the shared sample response and fresh runs.

frontend/src/features/provenance/chartData.test.js runs the same checks on the same
sample file (written by scripts/make_sample_response.py), against the browser's rows.
"""

import json
from pathlib import Path

import pytest

from backend import calculations, simulate as engine
from backend.rounding import exact_sum, rnd
from backend.schemas import SimulateResponse
from test_calculation_records import CASES, WX

SAMPLE = Path(__file__).resolve().parent.parent / "frontend/src/features/provenance/sample_response.json"
SAMPLE_MODE = "historical"  # scripts/make_sample_response.py REQUEST price_mode


def responses():
    yield "sample", SimulateResponse.model_validate(json.loads(SAMPLE.read_text())), SAMPLE_MODE
    for name, (req, ctx) in CASES.items():
        yield name, engine.simulate(req, wx=WX, context=ctx), req.price_mode


RESPONSES = list(responses())
IDS = [r[0] for r in RESPONSES]


def scopes(out):
    return [(scope, per_acre) for scope in ["farm"] + [b.id for b in out.blocks] for per_acre in (False, True)]


def present(pairs):
    return [v for _, v in pairs if v is not None]


@pytest.mark.parametrize("name,out,mode", RESPONSES, ids=IDS)
def test_margin_is_sales_minus_cost_on_every_row(name, out, mode):
    checked = 0
    for scope, per_acre in scopes(out):
        t = calculations.table_series(out, scope, per_acre)
        for (y, s), (_, c), (_, m) in zip(t["sales"], t["cost"], t["margin"]):
            if s is None or c is None:
                assert m is None
                continue
            assert m == s - c, (scope, per_acre, y)
            checked += 1
    for b in out.blocks:
        for r in b.yearly:
            if r.profit is not None:
                assert r.profit == r.revenue - r.cost
    for f in out.farm_totals:
        if f.profit is not None:
            assert f.profit == f.revenue - f.cost
    assert checked


@pytest.mark.parametrize("name,out,mode", RESPONSES, ids=IDS)
def test_sales_equal_harvest_times_the_price_used(name, out, mode):
    prices = engine._price_tables()[0]
    weights = {w.block_id: w for w in out.yield_weight}
    checked = 0
    for b in out.blocks:
        for r in b.yearly:
            if r.revenue is None:
                continue
            tons = next(x for x in weights[b.id].yearly if x.year == r.year).tons
            price = engine._lookup_price(prices, b.crop, r.year, mode, {}, b.crop)
            qty, _ = engine.sale_quantity(tons, price.unit, b.crop)
            assert r.revenue == rnd(qty * price.value), (b.id, r.year)
            checked += 1
    assert checked


@pytest.mark.parametrize("name,out,mode", RESPONSES, ids=IDS)
def test_farm_row_is_the_sum_of_crop_rows(name, out, mode):
    farm = calculations.table_series(out, "farm", False)
    crops = [calculations.table_series(out, b.id, False) for b in out.blocks]
    for i, (y, _) in enumerate(farm["harvest"]):
        h = [c["harvest"][i][1] for c in crops if c["harvest"][i][1] is not None]
        assert farm["harvest"][i][1] == (rnd(sum(h), 2) if h else None), y
        assert farm["water"][i][1] == rnd(sum(c["water"][i][1] for c in crops), 1), y
        for metric in ("sales", "cost", "margin"):
            vals = [c[metric][i][1] for c in crops if c[metric][i][1] is not None]
            assert farm[metric][i][1] == (sum(vals) if vals else None), (y, metric)


@pytest.mark.parametrize("name,out,mode", RESPONSES, ids=IDS)
def test_average_row_is_the_sum_over_the_years_with_data(name, out, mode):
    c = out.calculations
    for scope, per_acre in scopes(out):
        t = calculations.table_series(out, scope, per_acre)
        basis = "per_acre" if per_acre else "total"
        avgs = {}
        for metric in ("harvest", "sales", "cost", "water", "yield"):
            vals = present(t[metric])
            rid = f"table.{scope}.{basis}.{metric}"
            if not vals:
                assert rid not in c
                continue
            d = calculations.TABLE_DECIMALS[(metric, per_acre)]
            avgs[metric] = rnd(exact_sum(vals) / len(vals), d)
            assert c[rid]["value"] == avgs[metric], rid
            if metric == "harvest":
                lb = rnd(exact_sum(v * 2000 for v in vals) / len(vals))
                assert c[rid]["lb"]["value"] == lb, rid
        if "sales" in avgs:
            margins = present(t["margin"])
            assert c[f"table.{scope}.{basis}.margin"]["value"] == avgs["sales"] - avgs["cost"]
            # Before rounding, average margin and average sales - average cost are the same number.
            assert sum(margins) / len(margins) == pytest.approx(
                sum(present(t["sales"])) / len(margins) - sum(present(t["cost"])) / len(margins), abs=1e-6)
            if avgs["sales"]:
                m = avgs["sales"] - avgs["cost"]
                assert c[f"table.{scope}.{basis}.margin_pct"]["value"] == rnd(m / avgs["sales"] * 100, 1)


@pytest.mark.parametrize("name,out,mode", RESPONSES, ids=IDS)
def test_summary_cards_equal_the_whole_farm_table(name, out, mode):
    s, c = out.summary_stats, out.calculations
    t = calculations.table_series(out, "farm", False)
    assert s.total_profit == exact_sum(present(t["margin"]))
    assert s.avg_profit == c["table.farm.total.margin"]["value"]
    assert s.avg_cost == c["table.farm.total.cost"]["value"]
    assert s.avg_yield_tons == c["table.farm.total.harvest"]["value"]
    assert s.avg_water_applied_af == c["table.farm.total.water"]["value"]
    for key in ("avg_profit", "avg_cost", "avg_yield_tons", "avg_water_applied_af", "total_profit"):
        assert c[f"summary.{key}"]["value"] == getattr(s, key), key
    assert c["summary.avg_yield_tons"]["lb"]["value"] == c["table.farm.total.harvest"]["lb"]["value"]


def test_sample_file_is_current():
    """The committed sample matches what the generator writes, apart from source links
    that name the current commit."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_sample", SAMPLE.parents[4] / "scripts/make_sample_response.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fresh, saved = json.loads(mod.sample().model_dump_json()), json.loads(SAMPLE.read_text())
    for key in ("farm_totals", "blocks", "yield_weight", "summary_stats", "summary", "years"):
        assert fresh[key] == saved[key], key
