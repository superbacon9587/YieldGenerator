"""Auditable, year-specific inputs and arithmetic for public backtest results.

Provenance is emitted from the same Backtest used to produce the response. Source
links point to the committed input extracts, never an API key or a generic claim
that NASA supplied production costs.
"""
from __future__ import annotations
import csv
import re
import subprocess
from functools import cache
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlencode
import numpy as np
from backend import economics, reference, power_client, yield_weight

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/superbacon9587/YieldGenerator"

@cache
def revision():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return "main"

@cache
def records(path):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))

def source(label, path, rows=None):
    return {"label": label, "url": f"{REPO}/blob/{revision()}/{path}", "records": rows or []}

def matching_price(path, key, name, price):
    if price is None:
        return []
    return [r for r in records(path) if r[key] == name and int(r["year"]) == price.year]

def build(bt, response, wx):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    prices, utilities, defaults = engine._price_tables()
    blocks = []
    prepared = engine.prepare_weather(wx)
    for b, out in zip(req.blocks, response.blocks):
        base = ctx["baseline_yields"].get(b.crop)
        cost = ctx["production_costs"].get(b.crop)
        typical = median(r.relative_yield for r in out.yearly)
        params = reference.crop_params(b.crop)
        normal = engine.normal_heat_days(b, prepared)
        base_tons = yield_weight.baseline_tons_per_acre(b.crop, ctx) if base else None
        path = "data/validation/ca_county_yields.csv" if base and base["basis"] == "county" else "data/validation/ca_state_yields.csv"
        yield_rows = [r for r in records(path) if r["crop"] == b.crop and (base is None or base["basis"] != "county" or r.get("county") == ctx["county"])] if base else []
        if yield_rows and base and round(median(float(r["yield"]) for r in yield_rows), 3) != base["value"]:
            yield_rows = []  # injected/custom context has no matching committed extract
        cost_rows = [r for r in records("data/reference/prices/production_costs.csv") if r["crop"] == b.crop and cost and r["region"] == cost["region"] and r["cost_excl_water"] and float(r["cost_excl_water"]) == cost["cost_excl_water"]]
        cost_warnings = []
        for record in cost_rows:
            filename_year = re.search(r"(20[0-9]{2})\.pdf", record["source"])
            if filename_year and filename_year.group(1) != record["study_year"]:
                cost_warnings.append(f"Cost record study_year is {record['study_year']} but its cited filename contains {filename_year.group(1)}. This source metadata has not been reconciled; treat this cost as provisional.")
        if yield_rows and max(int(record["year"]) for record in yield_rows) > req.years[1]:
            cost_warnings.append("The baseline yield extract includes reference years after this backtest ends. This is a retrospective scenario using later reference data, not an out-of-sample historical prediction.")
        sources = [source("Baseline yield: exact input extract", path, yield_rows), source("Regional production-cost input extract", "data/reference/prices/production_costs.csv", cost_rows), source("Crop coefficients and their verification flags", "data/reference/crops.json", [reference.get_crop(b.crop)]), source("Water and pump assumptions", "data/reference/prices/defaults.json", [defaults]), source("Irrigation efficiencies", "data/reference/irrigation.json")]
        yearly = []
        for row in out.yearly:
            s = bt.seasons[b.id][row.year]
            price = engine._lookup_price(prices, b.crop, row.year, req.price_mode, {}, b.crop)
            electricity = engine._lookup_price(utilities, engine.ELECTRICITY_SERIES, row.year, req.price_mode, {}, "electricity")
            active = s.active
            etc, eta = float(s.balance.etc[active].sum()), float(s.balance.eta[active].sum())
            heat_penalty = min(max(s.heat_stress_days-normal, 0)*engine.HEAT_PENALTY_PER_DAY, engine.HEAT_PENALTY_MAX)
            harvest_tpa = base_tons * row.relative_yield / typical if base_tons is not None and typical else None
            water_cost = s.water_applied_af * bt.water_cost_per_af[row.year] if bt.water_cost_per_af[row.year] is not None else None
            production_cost = cost["cost_excl_water"] * b.acres if cost else None
            query = {"parameters": ",".join(power_client.PARAMETERS), "community": "AG", "latitude": bt.grid_cell[0], "longitude": bt.grid_cell[1], "start": s.start.strftime("%Y%m%d"), "end": s.end.strftime("%Y%m%d"), "format": "JSON"}
            climate = wx.loc[str(s.start):str(s.end)]
            yearly.append({"year": row.year, "season_start": str(s.start), "season_end": str(s.end),
                "displayed": row.model_dump(), "harvest_tons_per_acre": harvest_tpa,
                "harvest_tons": harvest_tpa*b.acres if harvest_tpa is not None else None,
                "baseline_yield": base, "baseline_tons_per_acre": base_tons, "median_relative_yield": typical,
                "crop_price": vars(price) if price else None, "electricity_price": vars(electricity) if electricity else None,
                "sale_quantity": economics.convert_quantity(harvest_tpa*b.acres, "TON", price.unit, b.crop) if harvest_tpa is not None and price else None,
                "revenue_unrounded": s.revenue, "cost_unrounded": s.cost, "profit_unrounded": s.profit,
                "production_cost_excl_water": production_cost, "production_cost_per_acre": cost["cost_excl_water"] if cost else None,
                "production_cost_source": cost, "source_warnings": cost_warnings, "water_cost": water_cost,
                "applied_water_unrounded_af": s.water_applied_af, "blended_water_price_per_af": bt.water_cost_per_af[row.year],
                "surface_share": req.optional.surface_water_share, "surface_price_per_af": ctx.get("surface_water_price_per_af"),
                "pump_lift_ft": defaults["well_lift_ft"], "pump_efficiency": defaults["pump_efficiency"],
                "electricity_dollars_per_kwh": economics.electricity_to_dollars_per_kwh(electricity.value, electricity.unit) if electricity else None,
                "net_irrigation_applied_mm": s.applied_net_mm, "irrigation_efficiency": s.efficiency,
                "etc_active_mm": etc, "eta_active_mm": eta, "etc_all_mm": float(s.balance.etc.sum()), "effective_rain_mm": float(s.balance.rain_eff.sum()),
                "ky": params["ky"], "heat_threshold_c": params["heat_stress_c"], "normal_heat_days": normal,
                "heat_penalty_fraction": heat_penalty, "gdd_base_c": params["gdd_base_c"],
                "kc": params["kc"], "stage_days": params["stage_days"], "soil": req.optional.soil,
                "weather_processing": {"missing_before_fill": {k: int(climate[k].isna().sum()) for k in engine.WEATHER_COLUMNS}, "rule": "Temperature and ET0 gaps are interpolated; missing rain is filled with zero. ET0 is clipped to zero or above."},
                "weather_source": {"label": f"NASA POWER daily input request: {s.start} to {s.end}", "url": power_client.API_URL+"?"+urlencode(query)},
                "price_source": source("Crop price record actually used", "data/reference/prices/crop_prices.csv", matching_price("data/reference/prices/crop_prices.csv", "crop", b.crop, price)),
                "electricity_source": source("Electricity price record actually used", "data/reference/prices/utilities.csv", matching_price("data/reference/prices/utilities.csv", "type", engine.ELECTRICITY_SERIES, electricity))})
        blocks.append({"id": b.id, "crop": b.crop, "acres": b.acres, "sources": sources, "yearly": yearly})
    totals = response.farm_totals
    financial = [r for r in totals if r.profit is not None]
    excluded = [{"block_id": b.id, "crop": b.crop, "years": [r.year for r in b.yearly if r.profit is None]} for b in response.blocks if any(r.profit is None for r in b.yearly)]
    return {"version": 1, "model_revision": revision(), "data_revision": revision(), "price_mode": req.price_mode,
        "cost_basis": "Regional reference-study estimates plus modeled water cost. No farmer operating expenses were supplied. The budget is a spending limit, not an expense input.",
        "money_basis": "Revenue uses the same median-normalized harvest quantity as the harvest display; costs use a fixed regional study plus modeled water. Dollar results are modeled margins, not observed farm accounts.",
        "validation_status": "Model estimates; source tracing does not establish predictive accuracy. Crop coefficients marked verify=true and pump/water assumptions still require review.",
        "rounding_note": "Calculations use unrounded internal values; crop dollar rows and farm totals are rounded to whole dollars. Displayed rounded inputs may differ slightly when multiplied.",
        "excluded_financial_blocks": excluded,
        "reconciliation": {"avg_revenue": mean(r.revenue for r in financial) if financial else None, "avg_cost": mean(r.cost for r in financial) if financial else None, "avg_profit": mean(r.profit for r in financial) if financial else None, "years": [r.year for r in financial]},
        "annual_totals": [r.model_dump() for r in totals], "blocks": blocks,
        "model_source": source("Exact model implementation", "backend/simulate.py"),
        "harvest_source": source("Harvest conversion and median scaling", "backend/yield_weight.py"),
        "weather_record": {"start": str(wx.index.min().date()), "end": str(wx.index.max().date()), "grid_cell": list(bt.grid_cell)}}


# ================================================================ calculation records
# One record per number shown with an information button:
#     {id, label, value, unit, decimals, formula_text, is_estimate,
#      steps: [{text, expr, result}],
#      inputs: [{name, value, unit, source, source_url, kind, is_estimate,
#                estimate_reason, not_estimate_reason}]}
# Every step's expr is plain arithmetic over the numbers printed in its text, so
# tests can re-evaluate it. The last step's result equals value, which is the
# number the response (and the UI) shows. Input kinds: farmer, nasa, nass
# (reported data), reference, constant, model.

import datetime as _dt
from backend import units

CROP_NAMES = {"almonds": "Almonds", "walnuts": "Walnuts", "processing_tomatoes": "Processing tomatoes",
              "corn": "Corn", "oats": "Oats", "alfalfa_hay": "Alfalfa"}
FARMER = "Farmer input"
SAFE = {"__builtins__": {}, "min": min, "max": max, "round": round, "sum": sum, "len": len,
        "abs": abs, "zip": zip}
MODEL_SRC = "YieldGenerator model, backend/simulate.py"
METRIC_LABELS = {"harvest": "Harvest", "sales": "Sales", "cost": "Cost", "margin": "Margin",
                 "margin_pct": "Margin percent", "water": "Water", "yield": "Yield"}


def file_url(path):
    return f"{REPO}/blob/{revision()}/{path}"


def evaluate(expr):
    return eval(expr, SAFE)  # noqa: S307, expressions are built here from numbers only


class N:
    """A number as it appears in a step: value plus display decimals. Exact values print
    without trailing zeros; values that need more digits to reproduce a result get them."""

    def __init__(self, value, d=2, money=False):
        self.v, self.d, self.money = float(value), d, money

    def _digits(self, k):
        if round(self.v, self.d) != self.v:
            return f"{abs(self.v):.{self.d + k}f}"
        s = f"{abs(self.v):.{self.d}f}"
        if self.money and self.d:
            if round(self.v) == self.v:
                return s.split(".")[0]
            whole, frac = s.split(".")
            return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"
        return s.rstrip("0").rstrip(".") if "." in s else s

    def disp(self, k=0):
        digits = self._digits(k)
        whole, _, frac = digits.partition(".")
        s = f"{int(whole):,}" + (f".{frac}" if frac else "")
        sign = "-" if self.v < 0 and float(digits) != 0 else ""
        return f"{sign}${s}" if self.money else f"{sign}{s}"

    def lit(self, k=0):
        s = self._digits(k)
        return f"(-{s})" if self.v < 0 and float(s) != 0 else s


class Record:
    def __init__(self, rid, label, unit, decimals, formula):
        self.id, self.label, self.unit, self.decimals, self.formula = rid, label, unit, decimals, formula
        self.steps, self.inputs, self.value = [], [], None

    def step(self, text, ops, expr, d, unit="", money=False, true=None, keep="full"):
        """Append '<text> = <result> <unit>'. Operand decimals grow until the printed
        arithmetic reproduces the rounded result."""
        exact = evaluate(expr.format(*[repr(o.v) for o in ops])) if true is None else true
        result = round(exact, d) + 0.0
        k = 0
        for k in range(9):
            if round(evaluate(expr.format(*[o.lit(k) for o in ops])), d) == result:
                break
        out = N(result, d, money)
        line = text.format(*[o.disp(k) for o in ops]) + " = " + out.disp()
        self.steps.append({"text": line + (f" {unit}" if unit else ""),
                           "expr": expr.format(*[o.lit(k) for o in ops]), "result": result})
        return out if keep == "rounded" else N(exact, d, money)

    def raw(self, text, expr, result):
        self.steps.append({"text": text, "expr": expr, "result": result})

    def inp(self, name, value, unit, source, url=None, kind="reference", estimate=None, why_not=None):
        self.inputs.append({"name": name, "value": value, "unit": unit, "source": source,
                            "source_url": url, "kind": kind, "is_estimate": bool(estimate),
                            "estimate_reason": estimate or None,
                            "not_estimate_reason": None if estimate else why_not})

    def out(self, value):
        self.value = value
        return {"id": self.id, "label": self.label, "value": value, "unit": self.unit,
                "decimals": self.decimals, "formula_text": self.formula,
                "is_estimate": any(i["is_estimate"] for i in self.inputs),
                "steps": self.steps, "inputs": self.inputs}


# ---------------------------------------------------------------- shared inputs

def crop_name(crop):
    return CROP_NAMES.get(crop, crop.replace("_", " "))


def block_name(b, blocks):
    name = crop_name(b.crop)
    return f"{name} {b.id}" if sum(x.crop == b.crop for x in blocks) > 1 else name


def years_text(years):
    return f"{years[0]} to {years[-1]}" if len(years) > 1 else str(years[0])


def span_text(values, d, money=False):
    vals = [v for v in values if v is not None]
    lo, hi = N(min(vals), d, money).disp(), N(max(vals), d, money).disp()
    return f"{len(vals)} values, {lo}" if lo == hi else f"{len(vals)} values, {lo} to {hi}"


def model_input(rec, name, value, unit, reason):
    rec.inp(name, value, unit, MODEL_SRC, file_url("backend/simulate.py"), "model", reason)


def acres_input(rec, b, blocks):
    rec.inp(f"{block_name(b, blocks)} area", b.acres, "acres", FARMER, kind="farmer")


def crop_field_input(rec, crop, field, name, value, unit):
    entry = reference.get_crop(crop)[field]
    reason = "Placeholder value still marked for checking in crops.json" if entry.get("verify") else None
    rec.inp(name, value, unit, f"crops.json {crop}.{field}: {entry['source']}",
            file_url("data/reference/crops.json"), "reference", reason,
            "Published coefficient copied from the cited FAO table")


def baseline_input(rec, crop, ctx):
    base = ctx["baseline_yields"][crop]
    county = base["basis"] == "county"
    path = "data/validation/ca_county_yields.csv" if county else "data/validation/ca_state_yields.csv"
    rec.inp(f"{crop_name(crop)} baseline yield (median)", base["value"], base["unit"].lower().replace(" ", ""),
            base["source"], file_url(path), "nass",
            None if county else "Statewide median, not enough county data for this location")


def baseline_tons_steps(rec, crop, ctx):
    """Steps that turn the NASS baseline into tons per acre. Returns N."""
    base = ctx["baseline_yields"][crop]
    u = units._normalize(base["unit"])
    v = N(base["value"], 3)
    if u == units.LB_PER_ACRE:
        return rec.step("Baseline {0} lb/acre / 2,000 lb/ton", [v], "{0}/2000", 6, "tons/acre")
    if u == units.BU_PER_ACRE:
        w = units.bushel_weight_lb(crop)
        rec.inp(f"{crop_name(crop)} bushel weight", w, "lb/bu", "USDA standard test weight, backend/units.py",
                file_url("backend/units.py"), "constant", why_not="Fixed USDA unit conversion")
        return rec.step("Baseline {0} bu/acre x {1} lb/bu / 2,000 lb/ton", [v, N(w, 0)], "{0}*{1}/2000", 6,
                        "tons/acre")
    return N(base["value"], 3)


def typical_ry(response_block):
    return median(r.relative_yield for r in response_block.yearly)


def ry_inputs(rec, b, out_block, year=None):
    ys = [r.year for r in out_block.yearly]
    if year is not None:
        row = next(r for r in out_block.yearly if r.year == year)
        model_input(rec, f"Relative yield {year}", row.relative_yield, "fraction",
                    "Model estimate from FAO-33 yield response and FAO-56 water balance")
    model_input(rec, f"Median relative yield, {years_text(ys)}", typical_ry(out_block), "fraction",
                "Model estimate: median of the modeled relative yields")


def water_price_input(rec, ctx):
    raw = json_defaults()["surface_water_price_per_af"]
    value = ctx.get("surface_water_price_per_af")
    src = raw.get("source", "")
    if ctx.get("county") != "Merced" or raw.get("value") != value:
        entry = raw.get("by_region", {}).get(ctx.get("cost_region") or "San Joaquin Valley North", {})
        if entry.get("value") == value:
            src = entry.get("source", src)
    reason = ("Team estimate, no district rate found" if "Team estimate" in src
              else "Typical district rate, not this farm's water bill")
    rec.inp("Surface water price", value, "$/acre-ft", f"defaults.json surface_water_price_per_af: {src}",
            file_url("data/reference/prices/defaults.json"), "reference", reason)


@cache
def json_defaults():
    import json
    return json.loads((ROOT / "data/reference/prices/defaults.json").read_text())


def share_input(rec, req):
    share = req.optional.surface_water_share
    if "surface_water_share" in req.optional.model_fields_set:
        rec.inp("Surface water share", share, "fraction", FARMER, kind="farmer")
    else:
        rec.inp("Surface water share", share, "fraction", "Default in backend/schemas.py OptionalIn",
                file_url("backend/schemas.py"), "reference", "Default assumption, 50% surface water")


def series_input(rec, name, pairs, d, unit, reason, money=False):
    vals = [v for _, v in pairs]
    model_input(rec, f"{name}, {years_text([y for y, _ in pairs])}", span_text(vals, d, money), unit, reason)


# ---------------------------------------------------------------- generic averages

def average_steps(rec, pairs, d_in, d_out, unit, money=False, divisor=None, d_mid=None):
    """Sum the yearly values, divide by the year count (and optionally by acres)."""
    if money:
        unit = "per acre" if unit.endswith("/acre") else ""
    mid_unit = "" if money else unit.replace("/acre", "")
    ops = [N(v, d_in, money) for _, v in pairs]
    years = [y for y, _ in pairs]
    if len(ops) == 1:
        total = ops[0]
        rec.raw(f"Only year {years[0]}: {total.disp()}" + (f" {unit}" if unit else ""), total.lit(), round(total.v, d_in) + 0.0)
    else:
        text = f"Sum of {len(ops)} yearly values ({years_text(years)}): " + " + ".join(
            "{%d}" % i for i in range(len(ops)))
        total = rec.step(text, ops, " + ".join("{%d}" % i for i in range(len(ops))), d_in,
                         mid_unit if divisor is not None else unit, money)
    n = N(len(ops), 0)
    if divisor is None:
        return rec.step("{0} / {1} years", [total, n], "{0}/{1}", d_out, unit, money)
    mean_ = rec.step("{0} / {1} years", [total, n], "{0}/{1}", d_mid if d_mid is not None else d_out + 2,
                     mid_unit, money)
    return rec.step("{0} / {1} acres", [mean_, N(divisor, 2)], "{0}/{1}", d_out, unit, money)


# ---------------------------------------------------------------- summary records

def summary_records(response, req, ctx):
    out = {}
    totals = response.farm_totals
    stats = response.summary_stats
    yr = years_text(response.years)
    money_years = [(t.year, t.profit) for t in totals if t.profit is not None]
    reason = "Model estimate: revenue from modeled harvest and NASS prices, cost from a regional study and modeled water"

    def money_avg(rid, label, field, value, d_out):
        pairs = [(t.year, getattr(t, field)) for t in totals if getattr(t, field) is not None]
        if not pairs or value is None:
            return
        rec = Record(rid, label, "$", 0, f"Sum of yearly farm {METRIC_LABELS.get(field, field).lower() if field != 'profit' else 'margin'} / number of years with price data, {yr}")
        series_input(rec, f"Yearly farm {'margin' if field == 'profit' else field}", pairs, 0, "$", reason, True)
        average_steps(rec, pairs, 0, d_out, "", money=True)
        out[rid] = rec.out(value)

    if stats is not None:
        money_avg("summary.avg_profit", "Estimated margin per year", "profit", stats.avg_profit, 0)
        money_avg("summary.avg_cost", "Estimated cost per year", "cost", stats.avg_cost, 0)
        revs = [t.revenue for t in totals if t.revenue is not None]
        money_avg("summary.avg_revenue", "Estimated sales per year", "revenue",
                  round(sum(revs) / len(revs), 2) if revs else None, 2)
        if stats.total_profit is not None and money_years:
            rec = Record("summary.total_profit", "Total estimated margin", "$", 0,
                         f"Sum of yearly farm margins (sales minus cost), {yr}")
            series_input(rec, "Yearly farm margin", money_years, 0, "$", reason, True)
            ops = [N(v, 0, True) for _, v in money_years]
            rec.step(f"Sum of {len(ops)} yearly margins: " + " + ".join("{%d}" % i for i in range(len(ops))),
                     ops, " + ".join("{%d}" % i for i in range(len(ops))), 0, money=True)
            out[rec.id] = rec.out(stats.total_profit)
        if stats.avg_relative_yield is not None:
            pairs = [(t.year, t.relative_yield) for t in totals]
            rec = Record("summary.avg_relative_yield", "Average relative yield", "%", 1,
                         f"Average over {yr} of the acre-weighted farm relative yield, x 100")
            series_input(rec, "Yearly farm relative yield (acre-weighted)", pairs, 3, "fraction",
                         "Model estimate from FAO-33 yield response and FAO-56 water balance")
            m = average_steps(rec, pairs, 3, 3, "")
            rec.step("{0} x 100", [m], "{0}*100", 1, "%")
            out[rec.id] = rec.out(round(stats.avg_relative_yield * 100, 1))
        if stats.avg_water_applied_af is not None:
            pairs = [(t.year, t.water_applied_af) for t in totals]
            rec = Record("summary.avg_water_applied_af", "Average water per year", "acre-ft", 1,
                         f"Sum of yearly farm water applied / number of years, {yr}")
            series_input(rec, "Yearly farm water applied", pairs, 1, "acre-ft",
                         "Model estimate from FAO-56 water balance")
            average_steps(rec, pairs, 1, 1, "acre-ft")
            out[rec.id] = rec.out(stats.avg_water_applied_af)
        if stats.avg_yield_tons is not None:
            out.update(harvest_summary(response, req, ctx))
    if money_years:
        rec = Record("summary.worst_profit", "Lowest yearly profit", "$", 0, f"Smallest yearly farm margin, {yr}")
        series_input(rec, "Yearly farm margin", money_years, 0, "$", reason, True)
        ops = [N(v, 0, True) for _, v in money_years]
        rec.step("Smallest of " + ", ".join("{%d}" % i for i in range(len(ops))), ops,
                 "min(" + ", ".join("{%d}" % i for i in range(len(ops))) + ")", 0, money=True)
        out[rec.id] = rec.out(min(v for _, v in money_years))
    out.update(ranking_records(response))
    budget = req.optional.budget_usd
    if budget is not None and all(t.cost is not None for t in totals):
        rec = Record("summary.years_over_budget", "Years over budget", "years", 0,
                     "Count of years where estimated farm cost is above the yearly budget")
        rec.inp("Yearly operating budget", budget, "$", FARMER, kind="farmer")
        series_input(rec, "Yearly farm cost", [(t.year, t.cost) for t in totals], 0, "$", reason, True)
        over = [t for t in totals if t.cost > budget]
        listed = ", ".join(f"{t.year} ({N(t.cost, 0, True).disp()})" for t in over) or "none"
        costs = ", ".join(N(t.cost, 0).lit() for t in totals)
        rec.raw(f"Years with cost above {N(budget, 0, True).disp()}: {listed} = {len(over)} years",
                f"len([c for c in [{costs}] if c > {N(budget, 2).lit()}])", len(over))
        out[rec.id] = rec.out(len(over))
    return out


def ranking_records(response):
    totals = response.farm_totals
    by_profit = all(t.profit is not None for t in totals)
    field, d, money = ("profit", 0, True) if by_profit else ("relative_yield", 3, False)
    what = "farm margin" if by_profit else "farm relative yield"
    years = [t.year for t in totals]
    vals = [getattr(t, field) for t in totals]
    out = {}
    for key, fn, pick, year in (("best_year", "max", -1, response.summary.best_year),
                                ("worst_year", "min", 0, response.summary.worst_year)):
        rec = Record(f"summary.{key}", f"Year with the {'highest' if fn == 'max' else 'lowest'} {what}", "year", 0,
                     f"Year with the {'highest' if fn == 'max' else 'lowest'} yearly {what}, {years_text(years)}")
        series_input(rec, f"Yearly {what}", list(zip(years, vals)), d, "$" if money else "fraction",
                     "Model estimate from the backtest", money)
        ops = [N(v, d, money) for v in vals]
        top = rec.step(f"{'Highest' if fn == 'max' else 'Lowest'} {what}: {fn}(" + ", ".join(
            "{%d}" % i for i in range(len(ops))) + ")", ops,
            f"{fn}(" + ", ".join("{%d}" % i for i in range(len(ops))) + ")", d, money=money)
        lits = ", ".join(N(v, d).lit() for v in vals)
        rec.raw(f"Year with {what} {top.disp()} = {year}",
                f"[y for y, v in zip([{', '.join(map(str, years))}], [{lits}]) if v == {N(top.v, d).lit()}][{pick}]",
                year)
        out[rec.id] = rec.out(year)
    return out


def harvest_summary(response, req, ctx):
    stats = response.summary_stats
    yr = years_text(response.years)
    rec = Record("summary.avg_yield_tons", "Estimated harvest per year", "tons", 2,
                 f"Sum over crops of (average harvest per acre x acres), averaged over {yr}")
    parts = []
    for b, w in zip(req.blocks, response.yield_weight):
        tons = [r.tons for r in w.yearly if r.tons is not None]
        if not tons:
            continue
        mean_b = sum(tons) / len(tons)
        acres_input(rec, b, req.blocks)
        baseline_input(rec, b.crop, ctx)
        series_input(rec, f"{block_name(b, req.blocks)} yearly harvest",
                     [(r.year, r.tons) for r in w.yearly if r.tons is not None], 2, "tons",
                     "Model estimate: NASS median yield scaled by modeled relative yield")
        parts.append(rec.step(f"{block_name(b, req.blocks)}: {{0}} tons/acre x {{1}} acres",
                              [N(mean_b / b.acres, 4), N(b.acres, 2)], "{0}*{1}", 4, "tons"))
    if len(parts) == 1:
        rec.step("Total, rounded to 0.01", parts, "{0}", 2, "tons")
    else:
        rec.step("Total = " + " + ".join("{%d}" % i for i in range(len(parts))), parts,
                 " + ".join("{%d}" % i for i in range(len(parts))), 2, "tons")
    return {rec.id: rec.out(stats.avg_yield_tons)}


# ---------------------------------------------------------------- block and year records

def season_inputs(rec, b, s, grid, url):
    rec.inp(f"Growing months {b.start_month} to {b.end_month}", f"{s.start} to {s.end}", "dates", FARMER,
            kind="farmer")


def block_year_records(bt, response, wx):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    prepared = engine.prepare_weather(wx)
    prices, utilities, defaults = engine._price_tables()
    weights = {w.block_id: w for w in response.yield_weight}
    out = {}
    lat, lon = bt.grid_cell
    for b, ob in zip(req.blocks, response.blocks):
        params = reference.crop_params(b.crop)
        name = block_name(b, req.blocks)
        normal = engine.normal_heat_days(b, prepared)
        typical = typical_ry(ob)
        w = weights.get(b.id)
        for r in ob.yearly:
            s = bt.seasons[b.id][r.year]
            days = prepared.loc[str(s.start):str(s.end)]
            query = {"parameters": ",".join(power_client.PARAMETERS), "community": "AG", "latitude": lat,
                     "longitude": lon, "start": s.start.strftime("%Y%m%d"), "end": s.end.strftime("%Y%m%d"),
                     "format": "JSON"}
            url = power_client.API_URL + "?" + urlencode(query)
            nasa = f"NASA POWER daily, grid cell {lat:g}, {lon:g}, {s.start} to {s.end}"
            key = f"block.{b.id}.{r.year}"
            n_days, n_active = len(days), int(s.active.sum())
            fao = "Model estimate from FAO-56 water balance"

            # crop water use
            rec = Record(f"{key}.crop_water_use_in", f"Crop water use, {name}, {r.year}", "in", 1,
                         "Sum over season days of (reference ET0 x crop coefficient Kc), mm / 25.4")
            season_inputs(rec, b, s, bt.grid_cell, url)
            rec.inp("Reference ET0, season total", round(float(days["et0_mm_day"].sum()), 2), "mm", nasa, url,
                    "model", "Model estimate: FAO-56 Penman-Monteith from NASA POWER weather")
            crop_field_input(rec, b.crop, "kc", "Crop coefficient Kc (ini, mid, end)",
                             f"{params['kc']['ini']}, {params['kc']['mid']}, {params['kc']['end']}", "")
            etc = rec.step(f"Sum over {n_days} days of daily ET0 x Kc", [N(float(s.balance.etc.sum()), 2)],
                           "{0}", 2, "mm")
            rec.step("{0} mm / 25.4 mm per inch", [etc], "{0}/25.4", 1, "in")
            out[rec.id] = rec.out(r.crop_water_use_in)

            # effective rain
            rec = Record(f"{key}.effective_rain_in", f"Effective rain, {name}, {r.year}", "in", 1,
                         "Sum over season days of rain stored in the root zone, mm / 25.4")
            season_inputs(rec, b, s, bt.grid_cell, url)
            rec.inp("Rain, season total", round(float(days["precip_mm_day"].sum()), 2), "mm", nasa, url, "nasa")
            rec.inp("Effective rain rule", f"rain under {engine.RAIN_THRESHOLD_MM:g} mm/day ignored, "
                    f"{engine.RAIN_EFFECTIVE_FRACTION:.0%} of larger rain counted", "",
                    "backend/simulate.py RAIN_THRESHOLD_MM, RAIN_EFFECTIVE_FRACTION (Dastane 1974, FAO paper 25)",
                    file_url("backend/simulate.py"), "constant",
                    "Fixed-percentage method, not measured infiltration")
            soil = reference.soils()[req.optional.soil]
            rec.inp(f"Soil water holding, {req.optional.soil}", soil["awc_mm_per_m"], "mm/m",
                    f"soils.json {req.optional.soil}: {soil['source']}", file_url("data/reference/soils.json"),
                    "reference", "Midpoint of the FAO-56 Table 19 range")
            rain = rec.step(f"Sum over {n_days} days of rain stored in the root zone",
                            [N(float(s.balance.rain_eff.sum()), 2)], "{0}", 2, "mm")
            rec.step("{0} mm / 25.4 mm per inch", [rain], "{0}/25.4", 1, "in")
            out[rec.id] = rec.out(r.effective_rain_in)

            # water applied
            rec = Record(f"{key}.water_applied_af", f"Water applied, {name}, {r.year}", "acre-ft", 1,
                         "Net irrigation (mm) / 304.8 mm per ft x acres / irrigation efficiency")
            model_input(rec, "Net irrigation applied", round(s.applied_net_mm, 2), "mm", fao)
            acres_input(rec, b, req.blocks)
            irr = reference.irrigation()[engine.IRRIGATION_KEYS.get(b.irrigation, b.irrigation)]
            rec.inp(f"Irrigation efficiency, {b.irrigation.replace('_', ' ')}", irr["efficiency"], "fraction",
                    f"irrigation.json: {irr['source']}", file_url("data/reference/irrigation.json"), "reference",
                    "Placeholder typical efficiency, marked for checking in irrigation.json" if irr.get("verify") else None,
                    "Published efficiency")
            if s.capped:
                rec.inp("Farm water limit", req.optional.water_available_af, "acre-ft/year", FARMER, kind="farmer")
            net = rec.step("{0} mm / 304.8 mm per ft x {1} acres", [N(s.applied_net_mm, 2), N(b.acres, 2)],
                           "{0}/304.8*{1}", 4, "acre-ft")
            rec.step("{0} acre-ft / {1} efficiency", [net, N(s.efficiency, 2)], "{0}/{1}", 1, "acre-ft")
            out[rec.id] = rec.out(r.water_applied_af)

            # relative yield
            rec = Record(f"{key}.relative_yield", f"Percent of full potential, {name}, {r.year}", "%", 1,
                         "(1 - Ky x (1 - actual ET / full ET)) - heat penalty, kept between 0 and 1, x 100")
            crop_field_input(rec, b.crop, "ky", "Yield response factor Ky", params["ky"], "")
            etc_a, eta_a = float(s.balance.etc[s.active].sum()), float(s.balance.eta[s.active].sum())
            model_input(rec, "Full crop ET, growing days", round(etc_a, 2), "mm", fao)
            model_input(rec, "Actual crop ET, growing days", round(eta_a, 2), "mm", fao)
            rec.inp("Heat days this season", s.heat_stress_days, "days", nasa, url, "nasa")
            rec.inp("Normal heat days (median of all seasons)", normal, "days",
                    f"NASA POWER daily, grid cell {lat:g}, {lon:g}, {prepared.index.min().date()} to "
                    f"{prepared.index.max().date()}", None, "nasa")
            rec.inp("Heat penalty", f"{engine.HEAT_PENALTY_PER_DAY} per extra day, up to {engine.HEAT_PENALTY_MAX}",
                    "fraction", "backend/simulate.py HEAT_PENALTY_PER_DAY, HEAT_PENALTY_MAX",
                    file_url("backend/simulate.py"), "constant", "Team assumption, not a published coefficient")
            if etc_a > 0:
                wf = rec.step("1 - {0} x (1 - {1} mm / {2} mm)", [N(params["ky"], 2), N(eta_a, 2), N(etc_a, 2)],
                              "1-{0}*(1-{1}/{2})", 4)
            else:
                rec.raw("No crop ET on growing days, water factor = 1", "1", 1)
                wf = N(1, 0)
            pen = rec.step("Heat penalty: min(max({0} - {1}, 0) x 0.0025, 0.10)",
                           [N(s.heat_stress_days, 0), N(normal, 1)], "min(max({0}-{1},0)*0.0025,0.10)", 4)
            ry = rec.step("{0} - {1}, kept between 0 and 1", [wf, pen], "min(max({0}-{1},0),1)", 3,
                          true=s.relative_yield, keep="rounded")
            rec.step("{0} x 100", [ry], "{0}*100", 1, "%")
            out[rec.id] = rec.out(round(r.relative_yield * 100, 1))

            # harvest per acre and total
            if w is not None:
                wr = next(x for x in w.yearly if x.year == r.year)
                if wr.tons_per_acre is not None:
                    for field, label, d in (("tons_per_acre", "Harvest per acre", 3), ("tons", "Total harvest", 2)):
                        rec = Record(f"{key}.{field}", f"{label}, {name}, {r.year}",
                                     "tons/acre" if field == "tons_per_acre" else "tons", d,
                                     "NASS median yield in tons/acre x relative yield / median relative yield"
                                     + (" x acres" if field == "tons" else ""))
                        baseline_input(rec, b.crop, ctx)
                        ry_inputs(rec, b, ob, r.year)
                        base = baseline_tons_steps(rec, b.crop, ctx)
                        if field == "tons":
                            acres_input(rec, b, req.blocks)
                            rec.step("{0} tons/acre x {1} / {2} x {3} acres",
                                     [base, N(r.relative_yield, 3), N(typical, 4), N(b.acres, 2)],
                                     "{0}*{1}/{2}*{3}", d, "tons")
                        else:
                            rec.step("{0} tons/acre x {1} / {2}", [base, N(r.relative_yield, 3), N(typical, 4)],
                                     "{0}*{1}/{2}", d, "tons/acre")
                        out[rec.id] = rec.out(getattr(wr, field))

            # heat days
            rec = Record(f"{key}.heat_stress_days", f"Heat days, {name}, {r.year}", "days", 0,
                         "Count of growing days with daily maximum temperature above the crop threshold")
            rec.inp("Daily maximum temperature", f"{n_active} growing days", "deg C", nasa, url, "nasa")
            crop_field_input(rec, b.crop, "heat_stress_c", "Heat threshold", params["heat_stress_c"], "deg C")
            rec.step(f"Growing days from {s.start} to {s.end} with maximum temperature above "
                     f"{params['heat_stress_c']:g} deg C", [N(s.heat_stress_days, 0)], "{0}", 0, "days")
            out[rec.id] = rec.out(r.heat_stress_days)

            # growing degree days
            rec = Record(f"{key}.gdd", f"Growing degree days, {name}, {r.year}", "deg C-days", 0,
                         "Sum over growing days of max(0, (Tmax + Tmin) / 2 - base temperature)")
            rec.inp("Daily maximum and minimum temperature", f"{n_active} growing days", "deg C", nasa, url, "nasa")
            crop_field_input(rec, b.crop, "gdd_base_c", "Base temperature", params["gdd_base_c"], "deg C")
            g = rec.step(f"Sum over {n_active} growing days of max(0, (Tmax + Tmin) / 2 - {params['gdd_base_c']:g})",
                         [N(s.gdd, 2)], "{0}", 2, "deg C-days")
            rec.step("{0} rounded to a whole number", [g], "round({0})", 0, "deg C-days")
            out[rec.id] = rec.out(r.gdd)

            # margin
            if r.profit is not None:
                out[f"{key}.profit"] = profit_record(f"{key}.profit", b, r, s, ob, bt, prices, utilities, defaults,
                                                     name, typical)
    return out


def profit_record(rid, b, r, s, ob, bt, prices, utilities, defaults, name, typical):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    rec = Record(rid, f"Estimated margin, {name}, {r.year}", "$", 0,
                 "Sales (baseline yield x acres x price x relative yield / median) minus cost "
                 "(regional cost x acres + water applied x water price)")
    base = ctx["baseline_yields"][b.crop]
    cost = ctx["production_costs"][b.crop]
    price = engine._lookup_price(prices, b.crop, r.year, req.price_mode, {}, b.crop)
    elec = engine._lookup_price(utilities, engine.ELECTRICITY_SERIES, r.year, req.price_mode, {}, "electricity")
    sale_unit = economics.normalize_unit(price.unit).lower()
    baseline_input(rec, b.crop, ctx)
    acres_input(rec, b, req.blocks)
    rows = matching_price("data/reference/prices/crop_prices.csv", "crop", b.crop, price)
    filled = req.price_mode == "historical" and price.year != r.year
    rec.inp(f"{crop_name(b.crop)} price, {price.year}", price.value, price.unit.replace(" ", ""),
            f"{rows[0]['source'] if rows else 'crop_prices.csv'}, {price.year}",
            file_url("data/reference/prices/crop_prices.csv"), "nass",
            f"Nearest year's price, no NASS price for {r.year}" if filled else None)
    ry_inputs(rec, b, ob, r.year)
    warn = ""
    for record in records("data/reference/prices/production_costs.csv"):
        m = re.search(r"(20[0-9]{2})\.pdf", record["source"])
        if record["crop"] == b.crop and record["region"] == cost["region"] and m and m.group(1) != record["study_year"] \
                and record["cost_excl_water"] and float(record["cost_excl_water"]) == cost["cost_excl_water"]:
            warn = f"; study year {record['study_year']} differs from the {m.group(1)} in the file name"
    away = f"; nearest region with a study ({cost['region']})" if ctx.get("cost_region") and ctx["cost_region"] != cost["region"] else ""
    rec.inp("Production cost excluding water", cost["cost_excl_water"], "$/acre", cost["source"],
            file_url("data/reference/prices/production_costs.csv"), "reference",
            "Regional reference budget from a UC Davis cost study, not this farm's expenses" + away + warn)
    model_input(rec, f"Water applied {r.year} (unrounded)", round(s.water_applied_af, 4), "acre-ft",
                "Model estimate from FAO-56 water balance")

    # sales
    qty = N(base["value"], 3)
    if economics.normalize_unit(base["unit"]) != economics.normalize_unit(price.unit):
        f_lb, t_lb = economics.unit_to_lb(base["unit"], b.crop), economics.unit_to_lb(price.unit, b.crop)
        qty = rec.step(f"Baseline {{0}} {base['unit'].lower()} x {{1}} lb / {{2}} lb per {sale_unit}",
                       [qty, N(f_lb, 0), N(t_lb, 0)], "{0}*{1}/{2}", 4, f"{sale_unit}/acre")
    typ = rec.step(f"Typical-year sales: {{0}} {sale_unit}/acre x {{1}} acres x {{2}} per {sale_unit}",
                   [qty, N(b.acres, 2), N(price.value, 2, True)], "{0}*{1}*{2}", 2, money=True)
    rev = rec.step("Sales: {0} x {1} / {2}", [typ, N(r.relative_yield, 3), N(typical, 4)], "{0}*{1}/{2}", 2,
                   money=True, true=s.revenue)
    # cost
    prod = rec.step("Production cost: {0} per acre x {1} acres", [N(cost["cost_excl_water"], 2, True), N(b.acres, 2)],
                    "{0}*{1}", 2, money=True)
    share = req.optional.surface_water_share
    share_input(rec, req)
    parts = []
    if share > 0:
        water_price_input(rec, ctx)
        parts.append((N(share, 2), N(ctx["surface_water_price_per_af"], 2)))
    if share < 1 and elec is not None:
        rec.inp("Well lift", defaults["well_lift_ft"], "ft",
                f"defaults.json well_lift_ft: {json_defaults()['well_lift_ft'].get('source', '')}",
                file_url("data/reference/prices/defaults.json"), "reference",
                f"Default assumption, {defaults['well_lift_ft']:g} ft well lift")
        rec.inp("Pump efficiency", defaults["pump_efficiency"], "fraction", "defaults.json pump_efficiency",
                file_url("data/reference/prices/defaults.json"), "reference",
                f"Default assumption, {defaults['pump_efficiency']:.0%} pump efficiency")
        rows = matching_price("data/reference/prices/utilities.csv", "type", engine.ELECTRICITY_SERIES, elec)
        rec.inp(f"Electricity price, {elec.year}", elec.value, elec.unit,
                f"{rows[0]['source'] if rows else 'utilities.csv'}, {elec.year}",
                file_url("data/reference/prices/utilities.csv"), "reference",
                "California average commercial rate (EIA), not this farm's tariff")
        rec.inp("Energy to lift 1 acre-ft by 1 ft", economics.KWH_PER_AF_FT, "kWh", "backend/economics.py KWH_PER_AF_FT",
                file_url("backend/economics.py"), "constant", why_not="Physical constant")
        kwh = N(elec.value, 2)
        if economics.normalize_unit(elec.unit) == "CENTS/KWH":
            kwh = rec.step("Electricity {0} cents/kWh / 100", [kwh], "{0}/100", 4, "$/kWh")
        pump = rec.step("Pumping: {0} ft x 1.02 kWh / {1} efficiency x {2} $/kWh",
                        [N(defaults["well_lift_ft"], 0), N(defaults["pump_efficiency"], 2), kwh],
                        "{0}*1.02/{1}*{2}", 4, "$/acre-ft")
        parts.append((N(1 - share, 2), pump))
    if len(parts) == 2:
        wp = rec.step("Water price: {0} x {1} + {2} x {3}", [parts[0][0], parts[0][1], parts[1][0], parts[1][1]],
                      "{0}*{1}+{2}*{3}", 4, "$/acre-ft", true=bt.water_cost_per_af[r.year])
    else:
        wp = rec.step("Water price: {0} x {1}", list(parts[0]), "{0}*{1}", 4, "$/acre-ft",
                      true=bt.water_cost_per_af[r.year])
    water = rec.step("Water cost: {0} acre-ft x {1} $/acre-ft", [N(s.water_applied_af, 4), wp], "{0}*{1}", 2,
                     money=True)
    total = rec.step("Cost: {0} + {1}", [prod, water], "{0}+{1}", 2, money=True, true=s.cost)
    rec.step("Margin: {0} - {1}", [rev, total], "{0}-{1}", 0, money=True, true=s.profit)
    return rec.out(r.profit)


# ---------------------------------------------------------------- data table average rows

def table_series(response, scope, per_acre):
    """{metric: [(year, total, divisor)]}: the data table under a chart shows total / divisor
    (divisor 1 for totals, acres for per acre). total is None when not available."""
    weights = {w.block_id: w for w in response.yield_weight}
    rows = {m: [] for m in ("harvest", "sales", "cost", "margin", "water", "yield")}
    if scope == "farm":
        total_acres = sum(b.acres for b in response.blocks)
        for t in response.farm_totals:
            y = t.year
            known = []
            for b in response.blocks:
                wr = next((r for r in weights[b.id].yearly if r.year == y), None) if b.id in weights else None
                if wr is not None and wr.tons is not None:
                    known.append((b.acres, wr.tons))
            m_acres = sum(b.acres for b in response.blocks
                          if next(r for r in b.yearly if r.year == y).profit is not None)
            h = sum(v for _, v in known) if known else None
            rows["harvest"].append((y, h, sum(a for a, _ in known) if per_acre else 1))
            for m, v in (("sales", t.revenue), ("cost", t.cost), ("margin", t.profit)):
                rows[m].append((y, v, m_acres if per_acre else 1))
            rows["water"].append((y, t.water_applied_af, total_acres if per_acre else 1))
            rows["yield"].append((y, t.relative_yield * 100, 1))
        return rows
    b = next(x for x in response.blocks if x.id == scope)
    w = weights.get(scope)
    div = b.acres if per_acre else 1
    for r in b.yearly:
        wr = next((x for x in w.yearly if x.year == r.year), None) if w else None
        rows["harvest"].append((r.year, (wr.tons_per_acre if per_acre else wr.tons) if wr else None, 1))
        for m, v in (("sales", r.revenue), ("cost", r.cost), ("margin", r.profit)):
            rows[m].append((r.year, v, div))
        rows["water"].append((r.year, r.water_applied_af, div))
        rows["yield"].append((r.year, r.relative_yield * 100, 1))
    return rows


TABLE_DECIMALS = {"harvest": 4, "sales": 2, "cost": 2, "margin": 2, "water": 2, "yield": 2}
TABLE_INPUT_DECIMALS = {"harvest": 2, "sales": 0, "cost": 0, "margin": 0, "water": 1, "yield": 1}
TABLE_REASONS = {
    "harvest": "Model estimate: NASS median yield scaled by modeled relative yield",
    "water": "Model estimate from FAO-56 water balance",
    "yield": "Model estimate from FAO-33 yield response and FAO-56 water balance"}
MONEY_REASON = "Model estimate: modeled harvest x NASS price, regional study cost plus modeled water"


def table_average(response, req, scope, per_acre, metric):
    """Average row cell: (Record, N) or None when the column has no values."""
    rows = [(y, t, dv) for y, t, dv in table_series(response, scope, per_acre)[metric]
            if t is not None and dv]
    if not rows:
        return None
    b = next((x for x in req.blocks if x.id == scope), None)
    who = "whole farm" if scope == "farm" else block_name(b, req.blocks)
    money = metric in ("sales", "cost", "margin")
    divided = per_acre and any(dv != 1 for _, _, dv in rows)
    base_unit = {"harvest": "tons", "water": "acre-ft", "yield": "%"}.get(metric, "$")
    unit = base_unit + ("/acre" if per_acre and metric != "yield" else "")
    d, d_in = TABLE_DECIMALS[metric], TABLE_INPUT_DECIMALS[metric]
    if metric == "harvest" and per_acre and scope != "farm":
        d_in = 3  # block harvest per acre comes straight from yield_weight tons_per_acre
    years = [y for y, _, _ in rows]
    label = METRIC_LABELS[metric].lower()
    rec = Record(f"table.{scope}.{'per_acre' if per_acre else 'total'}.{metric}",
                 f"Average {label}{' per acre' if unit.endswith('/acre') else ''}, {who}", unit, d,
                 f"Sum of the yearly {label} values / number of years with a value, {years_text(years)}"
                 + (" / acres" if divided else ""))
    reason = TABLE_REASONS.get(metric, MONEY_REASON)
    series_input(rec, f"Yearly {label}, {who}", [(y, t) for y, t, _ in rows], d_in, base_unit if money is False else "$",
                 reason, money)
    divs = {dv for _, _, dv in rows}
    if divided and len(divs) == 1:
        acres = divs.pop()
        rec.inp("Area for per acre values", acres, "acres",
                FARMER if scope != "farm" else "Farmer input: sum of the crop entry areas in this column",
                kind="farmer")
        v = average_steps(rec, [(y, t) for y, t, _ in rows], d_in, d, unit, money, divisor=acres, d_mid=d + 2)
    elif divided:
        rec.inp("Area for per acre values", "varies by year", "acres",
                "Farmer input: sum of the crop entry areas in this column", kind="farmer")
        v = average_steps(rec, [(y, t / dv) for y, t, dv in rows], 4, d, unit, money)
    else:
        v = average_steps(rec, [(y, t) for y, t, _ in rows], d_in, d, unit, money)
    return rec, v


def table_records(response, req, ctx):
    out = {}
    for scope in ["farm"] + [b.id for b in response.blocks]:
        b = next((x for x in req.blocks if x.id == scope), None)
        who = "whole farm" if scope == "farm" else block_name(b, req.blocks)
        for per_acre in (False, True):
            avgs = {}
            for metric in ("harvest", "sales", "cost", "margin", "water", "yield"):
                found = table_average(response, req, scope, per_acre, metric)
                if found:
                    rec, v = found
                    avgs[metric] = v
                    out[rec.id] = rec.out(round(v.v, rec.decimals) + 0.0)
            if "margin" in avgs and "sales" in avgs and avgs["sales"].v:
                rid = f"table.{scope}.{'per_acre' if per_acre else 'total'}.margin_pct"
                rec = Record(rid, f"Average margin percent, {who}", "%", 2, "Average margin / average sales x 100")
                model_input(rec, "Average margin", round(avgs["margin"].v, 2), "$", "Model estimate from the backtest")
                model_input(rec, "Average sales", round(avgs["sales"].v, 2), "$", "Model estimate from the backtest")
                v = rec.step("{0} / {1} x 100", [avgs["margin"], avgs["sales"]], "{0}/{1}*100", 2, "%")
                out[rid] = rec.out(round(v.v, 2) + 0.0)
    return out


# ---------------------------------------------------------------- entry points

def simulate_records(bt, response, wx):
    req, ctx = bt.request, bt.context
    out = summary_records(response, req, ctx)
    out.update(block_year_records(bt, response, wx))
    out.update(table_records(response, req, ctx))
    return out


def plan_block_records(blocks, resp, ctx):
    """Average margin and harvest of each optimizer plan block."""
    out = {}
    weights = {w.block_id: w for w in resp.yield_weight}
    yr = years_text(resp.years)
    for b, ob in zip(blocks, resp.blocks):
        name = block_name(b, blocks)
        pairs = [(r.year, r.profit) for r in ob.yearly if r.profit is not None]
        if pairs:
            rec = Record(f"block.{b.id}.avg_profit", f"Average margin, {name}", "$", 0,
                         f"Sum of yearly margins of this crop entry / number of years, {yr}")
            series_input(rec, f"Yearly margin, {name}", pairs, 0, "$",
                         "Model estimate: modeled harvest x NASS price, regional study cost plus modeled water", True)
            average_steps(rec, pairs, 0, 0, "", money=True)
            out[rec.id] = rec.out(round(sum(v for _, v in pairs) / len(pairs)))
        w = weights.get(b.id)
        if w is not None and w.avg_tons is not None:
            rec = Record(f"block.{b.id}.avg_yield_tons", f"Average harvest, {name}", "tons", 2,
                         "NASS median yield in tons/acre x average relative yield / median relative yield x acres")
            baseline_input(rec, b.crop, ctx)
            acres_input(rec, b, blocks)
            ry_inputs(rec, b, ob)
            series_input(rec, "Yearly relative yield", [(r.year, r.relative_yield) for r in ob.yearly], 3, "fraction",
                         "Model estimate from FAO-33 yield response and FAO-56 water balance")
            base = baseline_tons_steps(rec, b.crop, ctx)
            ry = [r.relative_yield for r in ob.yearly]
            ops = [N(v, 3) for v in ry]
            s = rec.step(f"Sum of {len(ops)} relative yields", ops, " + ".join("{%d}" % i for i in range(len(ops))), 3)
            m = rec.step("{0} / {1} years", [s, N(len(ry), 0)], "{0}/{1}", 6)
            rec.step("{0} tons/acre x {1} / {2} x {3} acres", [base, m, N(typical_ry(ob), 4), N(b.acres, 2)],
                     "{0}*{1}/{2}*{3}", 2, "tons")
            out[rec.id] = rec.out(w.avg_tons)
    return out


def difference_records(plan_stats, current_stats, plan_calcs, current_calcs):
    out = {}
    for key, label, unit, d, money in (("avg_profit", "Profit difference", "$", 0, True),
                                       ("avg_yield_tons", "Harvest difference", "tons", 2, False),
                                       ("avg_water_applied_af", "Water difference", "acre-ft", 1, False),
                                       ("avg_cost", "Cost difference", "$", 0, True)):
        p, c = getattr(plan_stats, key), getattr(current_stats, key)
        if p is None or c is None:
            continue
        rec = Record(f"difference.{key}", label, unit, d, "Plan average minus current farm average, per year")
        for who, v, calcs in (("Plan", p, plan_calcs), ("Current farm", c, current_calcs)):
            rec.inp(f"{who} average", v, unit, f"{who} backtest, summary_stats.{key}",
                    file_url("backend/optimize.py"), "model", "Model estimate from the backtest")
        rec.step("{0} - {1}", [N(p, d, money), N(c, d, money)], "{0}-{1}", d, "" if money else unit, money)
        out[rec.id] = rec.out(round(p - c, d) + 0.0)
    return out
