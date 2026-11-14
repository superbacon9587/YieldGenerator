"""Assumption and data_quality text describes results; it never gives advice.

Two scans:
  1. Every string constant (not docstrings) in the modules that write assumptions,
     data_quality notes, infeasible reasons, or binding sentences.
  2. The text actually returned by /api/simulate and /api/optimize code paths for a
     wide set of inputs: every California county in the region table, a county not
     in the table, a point outside California, missing prices, water limits,
     budgets, land over capacity, frost, infeasible and unprofitable optimizer runs.
"""

import ast
import re
from pathlib import Path

import pytest

from backend import optimize as opt, regions, simulate as engine
from backend.schemas import OptimizeRequest, SimulateRequest
from conftest import make_context, make_weather

ADVICE = re.compile(r"you should|we recommend|replace|switch to|\bbest\b", re.IGNORECASE)
BACKEND = Path(__file__).resolve().parent.parent / "backend"
TEXT_MODULES = ["regions.py", "simulate.py", "summary.py", "yield_weight.py", "optimize.py",
                "frost.py", "comparisons.py", "waste.py", "economics.py"]
WX = make_weather()


def advice_in(texts):
    return [t for t in texts if ADVICE.search(t)]


def string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_phrase_list_catches_advice():
    assert advice_in(["We recommend drip.", "You should check this.", "Replace it with yours.",
                      "Switch to drip.", "Best year: 2019.", "Ranked by farm profit."]) == [
        "We recommend drip.", "You should check this.", "Replace it with yours.",
        "Switch to drip.", "Best year: 2019."]


@pytest.mark.parametrize("module", TEXT_MODULES)
def test_no_advice_in_source_strings(module):
    assert advice_in(string_constants(BACKEND / module)) == []


def all_contexts():
    tables = regions._default_tables()
    contexts = [make_context()]
    for county in sorted(tables.county_region):
        contexts.append(regions.build_context({"state": "CA", "county": county, "in_california": True}))
    contexts.append(regions.build_context({"state": "CA", "county": "Nowhere", "in_california": True}))
    contexts.append(regions.build_context({"state": "NV", "county": "Washoe", "in_california": False}))
    return contexts


ALL_CROPS = [
    {"id": "a", "crop": "almonds", "acres": 30, "irrigation": "flood", "start_month": 1, "end_month": 12},
    {"id": "w", "crop": "walnuts", "acres": 10, "irrigation": "drip", "start_month": 1, "end_month": 12},
    {"id": "h", "crop": "alfalfa_hay", "acres": 10, "irrigation": "sprinkler", "start_month": 1, "end_month": 12},
    {"id": "t", "crop": "processing_tomatoes", "acres": 10, "irrigation": "drip", "start_month": 3, "end_month": 7},
    {"id": "c", "crop": "corn", "acres": 10, "irrigation": "flood", "start_month": 5, "end_month": 9},
    {"id": "o", "crop": "oats", "acres": 10, "irrigation": "sprinkler", "start_month": 12, "end_month": 4},
]


def engine_ready(ctx) -> bool:
    """False for contexts the engine rejects. Known case: NASS county rows of 0.0 make a
    zero median baseline (San Bernardino corn, Ventura oats), which LocationContext
    refuses. That is a data loading issue in backend/regions.py, not a wording one."""
    try:
        engine.LocationContext.model_validate(ctx)
        return True
    except ValueError:
        return False


def test_no_advice_in_simulate_text():
    found, ran = [], 0
    for ctx in all_contexts():
        found += advice_in(ctx["data_quality"])
        if not engine_ready(ctx):
            continue
        ran += 1
        for extra in ({}, {"price_mode": "historical",
                           "optional": {"water_available_af": 40, "budget_usd": 1000,
                                        "water_applied_af": 500, "soil": "sand"},
                           "available_acres": 20}):
            req = SimulateRequest.model_validate({
                "location": {"lat": 37.3, "lon": -120.48}, "years": [2001, 2004],
                "blocks": ALL_CROPS, **extra})
            resp = engine.simulate(req, wx=WX, context=ctx, include_comparisons=(ran == 1))
            found += advice_in(resp.assumptions)
            found += advice_in([f.message for f in resp.waste_flags])
            found += advice_in([c.excludes for c in resp.comparisons])
    assert ran >= 10
    assert found == []


def test_no_advice_in_optimize_text():
    base = {"location": {"lat": 37.3, "lon": -120.48}, "years": [2001, 2004],
            "available_acres": 100, "budget_usd": 300_000}
    cases = [
        {},
        {"objective": "production_value", "price_mode": "historical", "water_available_af": 80},
        {"objective": "profit_per_af", "allow_new_perennials": True},
        {"current_farm": {"blocks": ALL_CROPS[:1]}, "budget_usd": 1000},     # locked acres too costly
        {"budget_usd": 10},                                                 # nothing fits
        {"allowed_crops": ["walnuts"]},                                     # no options
    ]
    found, statuses = [], set()
    for ctx in (make_context(), all_contexts()[1], all_contexts()[-1]):
        for case in cases:
            r = opt.optimize(OptimizeRequest.model_validate({**base, **case}), wx=WX, context=ctx)
            statuses.add(r.status)
            texts = r.assumptions + r.binding_constraints + [a.label for a in r.alternatives]
            texts += [t for t in (r.infeasible_reason, r.error_detail) if t]
            found += advice_in(texts)
    assert {"infeasible", "optimal"} <= statuses
    assert found == []
