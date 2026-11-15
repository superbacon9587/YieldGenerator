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
            m = s.money or {}
            water_cost = m["surface"] + m["groundwater"] if m else None
            production_cost = m.get("production")
            query = {"parameters": ",".join(power_client.PARAMETERS), "community": "AG", "latitude": bt.grid_cell[0], "longitude": bt.grid_cell[1], "start": s.start.strftime("%Y%m%d"), "end": s.end.strftime("%Y%m%d"), "format": "JSON"}
            climate = wx.loc[str(s.start):str(s.end)]
            yearly.append({"year": row.year, "season_start": str(s.start), "season_end": str(s.end),
                "displayed": row.model_dump(), "harvest_tons_per_acre": harvest_tpa,
                "harvest_tons": harvest_tpa*b.acres if harvest_tpa is not None else None,
                "harvest_tons_rounded": m.get("tons"),
                "baseline_yield": base, "baseline_tons_per_acre": base_tons, "median_relative_yield": typical,
                "crop_price": vars(price) if price else None, "electricity_price": vars(electricity) if electricity else None,
                "sale_quantity": m.get("qty"),
                "revenue_unrounded": m.get("revenue_exact"), "cost_unrounded": m.get("cost_exact"),
                "profit_unrounded": m["revenue_exact"] - m["cost_exact"] if m else None,
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
# One record per number shown with an information button. A person can redo every
# record by hand from the box alone:
#     {id, label, value, unit, decimals, formula_text, rounding, is_estimate,
#      steps: [{text, expr, result, round}],
#      inputs: [{name, value, unit, source, source_url, kind, is_estimate,
#                estimate_reason, not_estimate_reason}],
#      lb: the same record in pounds (weight records only)}
# Rules (tests/test_hand_calculator.py):
#   * expr uses only + - * / and parentheses on numbers that are input values or
#     earlier step results; every conversion factor and count is an input;
#   * result = expr, rounded half up to `round` decimals when round is set;
#   * the last result equals value, the number the response and the UI show.
# Values from a model (water balance, relative yield) are inputs tagged as estimates.
# Input kinds: farmer, nasa, nass (reported data), reference, constant, model.

import re as _re
from backend import units
from backend.rounding import exact_sum, mean, rnd

CROP_NAMES = {"almonds": "Almonds", "walnuts": "Walnuts", "processing_tomatoes": "Processing tomatoes",
              "corn": "Corn", "oats": "Oats", "alfalfa_hay": "Alfalfa"}
FARMER = "Farmer input"
MODEL_SRC = "YieldGenerator model, backend/simulate.py"
METRIC_LABELS = {"harvest": "harvest", "sales": "sales", "cost": "cost", "margin": "margin",
                 "margin_pct": "margin percent", "water": "water", "yield": "yield"}
ROUND_MONEY = "Dollars rounded to the nearest $1."


# ---------------------------------------------------------------- safe arithmetic

_TOKEN = _re.compile(r"\s*(?:(\d+(?:\.\d+)?)|(.))")


def tokens(expr):
    out = []
    for number, op in _TOKEN.findall(expr):
        if number:
            out.append(float(number))
        elif op.strip():
            if op not in "+-*/()":
                raise ValueError(f"Not basic arithmetic: {op!r} in {expr!r}")
            out.append(op)
    return out


def evaluate(expr):
    """+ - * / and parentheses, left to right with the usual precedence. No eval()."""
    toks, pos = tokens(expr), 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def atom():
        t = take()
        if t == "(":
            v = add()
            if take() != ")":
                raise ValueError(f"Unbalanced parentheses in {expr!r}")
            return v
        if t == "-":
            return -atom()
        if isinstance(t, float):
            return t
        raise ValueError(f"Unexpected {t!r} in {expr!r}")

    def mul():
        v = atom()
        while peek() in ("*", "/"):
            v = v * atom() if take() == "*" else v / atom()
        return v

    def add():
        v = mul()
        while peek() in ("+", "-"):
            v = v + mul() if take() == "+" else v - mul()
        return v

    v = add()
    if pos != len(toks):
        raise ValueError(f"Trailing tokens in {expr!r}")
    return v


def numbers_in(expr):
    return [t for t in tokens(expr) if isinstance(t, float)]


# ---------------------------------------------------------------- printing

def plain(v):
    """Shortest exact text for a number with at most 6 decimals: 2000, 0.934, 3520.3."""
    s = f"{abs(v):.6f}".rstrip("0").rstrip(".")
    return ("-" if v < 0 and s != "0" else "") + s


def shown(v, money=False, decimals=None):
    """Number with commas. Money gets a $ and, when it has cents, 2 or more decimals."""
    if decimals is not None:
        body = f"{abs(v):,.{decimals}f}"
    else:
        whole, _, frac = plain(abs(v)).partition(".")
        if money and frac:
            frac = frac.ljust(2, "0")
        body = f"{int(whole):,}" + (f".{frac}" if frac else "")
    sign = "-" if v < 0 and float(body.replace(",", "")) != 0 else ""
    return f"{sign}${body}" if money else f"{sign}{body}"


class N:
    """A number shown in the box. value is exactly what the text says."""

    def __init__(self, value, money=False, decimals=None):
        self.value = float(plain(value)) if decimals is None else rnd(value, decimals)
        self.money, self.decimals = money, decimals

    @property
    def text(self):
        return shown(self.value, self.money, self.decimals)

    @property
    def lit(self):
        p = plain(self.value)
        return f"({p})" if self.value < 0 else p


class Record:
    def __init__(self, rid, label, unit, decimals, formula, rounding):
        self.id, self.label, self.unit, self.decimals = rid, label, unit, decimals
        self.formula, self.rounding = formula, rounding
        self.steps, self.inputs = [], []

    def inp(self, name, value, unit, source, url=None, kind="reference", estimate=None, why_not=None,
            money=False):
        self.inputs.append({"name": name, "value": value, "unit": unit, "source": source,
                            "source_url": url, "kind": kind, "is_estimate": bool(estimate),
                            "estimate_reason": estimate or None,
                            "not_estimate_reason": None if estimate else why_not})
        return N(value, money) if isinstance(value, (int, float)) else None

    def step(self, text, ops, expr, unit="", round_to=None, money=False):
        """Append '<text> = <result> <unit>'; ops fill {0}, {1}... in text and expr."""
        e = expr.format(*[o.lit for o in ops])
        exact = evaluate(e)
        out = N(exact, money, round_to)
        u = f" {unit}" if unit else ""
        line = text.format(*[o.text for o in ops]) + " = "
        if round_to is not None and float(plain(exact)) != out.value:
            line += f"{shown(float(plain(exact)), money)}{u}, rounded to {out.text}{u}"
        else:
            line += f"{out.text}{u}"
        self.steps.append({"text": line, "expr": e, "result": out.value, "round": round_to})
        return out

    def out(self, value, lb=None):
        rec = {"id": self.id, "label": self.label, "value": value, "unit": self.unit,
               "decimals": self.decimals, "formula_text": self.formula, "rounding": self.rounding,
               "is_estimate": any(i["is_estimate"] for i in self.inputs),
               "steps": self.steps, "inputs": self.inputs}
        if lb is not None:
            rec["lb"] = lb
        return rec


# ---------------------------------------------------------------- shared inputs

def file_url(path):
    return f"{REPO}/blob/{revision()}/{path}"


def crop_name(crop):
    return CROP_NAMES.get(crop, crop.replace("_", " "))


def block_name(b, blocks):
    name = crop_name(b.crop)
    return f"{name} {b.id}" if sum(x.crop == b.crop for x in blocks) > 1 else name


def years_text(years):
    return f"{years[0]} to {years[-1]}" if len(years) > 1 else str(years[0])


def model_input(rec, name, value, unit, reason, money=False):
    return rec.inp(name, value, unit, MODEL_SRC, file_url("backend/simulate.py"), "model", reason, money=money)


def const(rec, name, value, unit, source, why="Unit conversion", path="backend/units.py"):
    return rec.inp(name, value, unit, source, file_url(path), "constant", why_not=why)


def lb_per_ton(rec):
    return const(rec, "Pounds per ton", 2000, "lb/ton", "US short ton, backend/units.py LB_PER_TON")


def percent_factor(rec):
    return const(rec, "Percent per whole", 100, "%", "Fraction x 100 = percent", "Definition of percent")


def count_input(rec, n, what="Years with data"):
    return rec.inp(what, n, "years", "Count of the yearly values listed above", None, "constant",
                   why_not="Count of listed values")


def acres_input(rec, b, blocks):
    return rec.inp(f"{block_name(b, blocks)} area", b.acres, "acres", FARMER, kind="farmer")


def baseline_input(rec, crop, ctx):
    base = ctx["baseline_yields"][crop]
    county = base["basis"] == "county"
    path = "data/validation/ca_county_yields.csv" if county else "data/validation/ca_state_yields.csv"
    return rec.inp(f"{crop_name(crop)} baseline yield (NASS median)", base["value"],
                   base["unit"].lower().replace(" ", ""), base["source"], file_url(path), "nass",
                   None if county else "Statewide median, not enough county data for this location")


def harvest_ops(rec, b, ry, typical, ctx, blocks, with_acres):
    """Inputs and the single expression that turns the NASS baseline into harvest.

    Same order of operations as backend/yield_weight.py, so the result is exact."""
    base = ctx["baseline_yields"][b.crop]
    u = units._normalize(base["unit"])
    v = baseline_input(rec, b.crop, ctx)
    ry_n = model_input(rec, "Relative yield this year", ry, "fraction",
                       "Model estimate from FAO-33 yield response (Ky) and FAO-56 water balance")
    typ_n = model_input(rec, "Median relative yield over the backtest years", typical, "fraction",
                        "Model estimate: median of the modeled relative yields")
    if u == units.LB_PER_ACRE:
        ops, text, expr = [v, lb_per_ton(rec)], "{0} lb/acre / {1} lb/ton", "{0}/{1}"
    elif u == units.BU_PER_ACRE:
        w = const(rec, f"{crop_name(b.crop)} bushel weight", units.bushel_weight_lb(b.crop), "lb/bu",
                  "USDA standard test weight, backend/units.py BUSHEL_WEIGHT_LB")
        ops, text, expr = [v, w, lb_per_ton(rec)], "{0} bu/acre x {1} lb/bu / {2} lb/ton", "{0}*{1}/{2}"
    else:
        ops, text, expr = [v], "{0} tons/acre", "{0}"
    k = len(ops)
    ops = ops + [ry_n, typ_n]
    text += f" x {{{k}}} / {{{k + 1}}}"
    expr += f"*{{{k}}}/{{{k + 1}}}"
    if with_acres:
        ops.append(acres_input(rec, b, blocks))
        text += f" x {{{k + 2}}} acres"
        expr += f"*{{{k + 2}}}"
    return text, ops, expr


def share_input(rec, req):
    share = req.optional.surface_water_share
    if "surface_water_share" in req.optional.model_fields_set:
        return rec.inp("Surface water share", share, "fraction", FARMER, kind="farmer")
    return rec.inp("Surface water share", share, "fraction", "Default in backend/schemas.py OptionalIn",
                   file_url("backend/schemas.py"), "reference", "Default assumption, 50% surface water")


@cache
def json_defaults():
    import json
    return json.loads((ROOT / "data/reference/prices/defaults.json").read_text())


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
    return rec.inp("Surface water price", value, "$/acre-ft", f"defaults.json surface_water_price_per_af: {src}",
                   file_url("data/reference/prices/defaults.json"), "reference", reason, money=True)


def yearly_inputs(rec, name, pairs, unit, reason, money=False):
    return [model_input(rec, f"{name}, {y}", v, unit, reason, money) for y, v in pairs]


def sum_step(rec, ops, unit="", money=False, what="yearly values"):
    if len(ops) == 1:
        return rec.step("Only one yearly value", ops, "{0}", unit, money=money)
    idx = range(len(ops))
    return rec.step(f"Sum of {len(ops)} {what}: " + " + ".join("{%d}" % i for i in idx), ops,
                    " + ".join("{%d}" % i for i in idx), unit, money=money)


def average_steps(rec, ops, round_to, unit="", money=False, scale=None):
    """Sum, optionally x a conversion factor, then / number of years, rounded."""
    total = sum_step(rec, ops, "tons" if scale else unit, money)
    if scale is not None:
        total = rec.step("{0} tons x {1} lb/ton", [total, scale], "{0}*{1}", "lb")
    n = count_input(rec, len(ops))
    return rec.step("{0} / {1} years", [total, n], "{0}/{1}", unit, round_to, money)


def lb_variant(rec_factory, steps_fn):
    """Build the pounds version of a weight record with the same inputs plus 2,000 lb/ton."""
    rec = rec_factory()
    steps_fn(rec)
    return rec


# ---------------------------------------------------------------- summary records

MONEY_REASON = "Model estimate: modeled harvest x NASS price, minus regional study cost and modeled water"


def summary_records(response, req, ctx):
    out = {}
    totals = response.farm_totals
    stats = response.summary_stats
    yr = years_text(response.years)
    money_rows = [t for t in totals if t.profit is not None]

    def money_average(rid, label, field, value):
        pairs = [(t.year, getattr(t, field)) for t in totals if getattr(t, field) is not None]
        if not pairs or value is None:
            return
        word = {"revenue": "sales", "cost": "cost"}[field]
        rec = Record(rid, label, "$", 0, f"Sum of yearly farm {word} / number of years with price data, {yr}",
                     ROUND_MONEY)
        ops = yearly_inputs(rec, f"Farm {word}", pairs, "$", MONEY_REASON, True)
        average_steps(rec, ops, 0, money=True)
        out[rid] = rec.out(value)

    if stats is not None and money_rows:
        money_average("summary.avg_cost", "Estimated cost per year", "cost", stats.avg_cost)
        avg_rev = rnd(mean(t.revenue for t in money_rows))
        money_average("summary.avg_revenue", "Estimated sales per year", "revenue", avg_rev)
        rec = Record("summary.avg_profit", "Estimated margin per year", "$", 0,
                     f"Average yearly sales - average yearly cost, {yr}", ROUND_MONEY + " Averages first, then subtracted.")
        s_ops = yearly_inputs(rec, "Farm sales", [(t.year, t.revenue) for t in money_rows], "$", MONEY_REASON, True)
        c_ops = yearly_inputs(rec, "Farm cost", [(t.year, t.cost) for t in money_rows], "$", MONEY_REASON, True)
        n = count_input(rec, len(money_rows))
        s_avg = rec.step("Average sales: {0} / {1} years", [sum_step(rec, s_ops, money=True, what="yearly sales values"), n],
                         "{0}/{1}", round_to=0, money=True)
        c_avg = rec.step("Average cost: {0} / {1} years", [sum_step(rec, c_ops, money=True, what="yearly cost values"), n],
                         "{0}/{1}", round_to=0, money=True)
        rec.step("Margin: {0} - {1}", [s_avg, c_avg], "{0}-{1}", money=True)
        out[rec.id] = rec.out(stats.avg_profit)
        rec = Record("summary.total_profit", "Total estimated margin", "$", 0,
                     f"Sum of yearly farm margins (sales - cost), {yr}", ROUND_MONEY)
        ops = yearly_inputs(rec, "Farm margin", [(t.year, t.profit) for t in money_rows], "$", MONEY_REASON, True)
        sum_step(rec, ops, money=True, what="yearly margins")
        out[rec.id] = rec.out(stats.total_profit)
    if stats is not None and stats.avg_relative_yield is not None:
        rec = Record("summary.avg_relative_yield", "Average relative yield", "%", 1,
                     f"Average of the yearly acre-weighted farm relative yield, x 100, {yr}",
                     "Average rounded to 0.001, then shown as a percent.")
        ops = yearly_inputs(rec, "Farm relative yield", [(t.year, t.relative_yield) for t in totals], "fraction",
                            "Model estimate from FAO-33 yield response and FAO-56 water balance")
        m = average_steps(rec, ops, 3)
        rec.step("{0} x {1}", [m, percent_factor(rec)], "{0}*{1}", "%", 1)
        out[rec.id] = rec.out(rnd(stats.avg_relative_yield * 100, 1))
    if stats is not None and stats.avg_water_applied_af is not None:
        rec = Record("summary.avg_water_applied_af", "Average water per year", "acre-ft", 1,
                     f"Sum of yearly farm water applied / number of years, {yr}", "Water rounded to 0.1 acre-ft.")
        ops = yearly_inputs(rec, "Farm water applied", [(t.year, t.water_applied_af) for t in totals], "acre-ft",
                            "Model estimate from FAO-56 water balance")
        average_steps(rec, ops, 1, "acre-ft")
        out[rec.id] = rec.out(stats.avg_water_applied_af)
    if stats is not None and stats.avg_yield_tons is not None:
        found = table_average(response, req, "farm", False, "harvest")
        if found:
            rec_t, rec_lb = found
            out["summary.avg_yield_tons"] = {**rec_t, "id": "summary.avg_yield_tons",
                                             "label": "Estimated harvest per year",
                                             "lb": {**rec_lb, "id": "summary.avg_yield_tons",
                                                    "label": "Estimated harvest per year"}}
    out.update(ranking_records(response))
    budget = req.optional.budget_usd
    if budget is not None and totals and all(t.cost is not None for t in totals):
        rec = Record("summary.years_over_budget", "Years over budget", "years", 0,
                     "Count of years where estimated farm cost is above the yearly budget",
                     "Whole years, no rounding.")
        b = rec.inp("Yearly operating budget", budget, "$", FARMER, kind="farmer", money=True)
        costs = yearly_inputs(rec, "Farm cost", [(t.year, t.cost) for t in totals], "$", MONEY_REASON, True)
        over = [(t, c) for t, c in zip(totals, costs) if t.cost > budget]
        for t, c in over:
            rec.step(f"{t.year}: cost {{0}} - budget {{1}}", [c, b], "{0}-{1}", "above the budget", money=True)
        if over:
            one = rec.inp("Each year above the budget counts as", 1, "year", "Counting rule", None, "constant",
                          why_not="Counting rule")
            rec.step(" + ".join(["{0}"] * len(over)) + " (years above)", [one], "+".join(["{0}"] * len(over)), "years")
        else:
            zero = rec.inp("Years above the budget", 0, "years", "No year's cost is above the budget",
                           None, "constant", why_not="Count of the listed years")
            rec.step("No year is above the budget", [zero], "{0}", "years")
        out[rec.id] = rec.out(len(over))
    return out


def ranking_records(response):
    """The best and worst year are a selection, not arithmetic: the record lists every
    yearly value and shows the selected year's value."""
    totals = response.farm_totals
    by_profit = all(t.profit is not None for t in totals)
    what = "farm margin" if by_profit else "farm relative yield"
    out = {}
    if not totals:
        return out
    for key, pick in (("best_year", max), ("worst_year", min)):
        vals = [(t.year, t.profit if by_profit else t.relative_yield) for t in totals]
        year = response.summary.best_year if key == "best_year" else response.summary.worst_year
        chosen = next(v for y, v in vals if y == year)
        word = "highest" if pick is max else "lowest"
        rec = Record(f"summary.{key}", f"Year with the {word} {what}", "$" if by_profit else "fraction",
                     0 if by_profit else 3, f"The year whose {what} is the {word} of the listed years",
                     ROUND_MONEY if by_profit else "Relative yield to 0.001.")
        ops = yearly_inputs(rec, what.capitalize(), vals, "$" if by_profit else "fraction",
                            "Model estimate from the backtest", by_profit)
        idx = [y for y, _ in vals].index(year)
        rec.step(f"{word.capitalize()} of the {len(vals)} listed values, year {year}", [ops[idx]], "{0}",
                 money=by_profit)
        out[rec.id] = rec.out(chosen)
        if by_profit and key == "worst_year":
            out["summary.worst_profit"] = {**rec.out(chosen), "id": "summary.worst_profit",
                                           "label": "Lowest yearly farm margin"}
    if not by_profit and any(t.profit is not None for t in totals):
        pairs = [(t.year, t.profit) for t in totals if t.profit is not None]
        y, v = min(pairs, key=lambda p: p[1])
        rec = Record("summary.worst_profit", "Lowest yearly farm margin", "$", 0,
                     "The lowest of the listed yearly farm margins", ROUND_MONEY)
        ops = yearly_inputs(rec, "Farm margin", pairs, "$", "Model estimate from the backtest", True)
        rec.step(f"Lowest of the {len(pairs)} listed values, year {y}", [ops[[p[0] for p in pairs].index(y)]],
                 "{0}", money=True)
        out[rec.id] = rec.out(v)
    return out


# ---------------------------------------------------------------- block and year records

def block_year_records(bt, response, wx):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    weights = {w.block_id: w for w in response.yield_weight}
    out = {}
    lat, lon = bt.grid_cell
    for b, ob in zip(req.blocks, response.blocks):
        params = reference.crop_params(b.crop)
        name = block_name(b, req.blocks)
        typical = median(r.relative_yield for r in ob.yearly)
        w = weights.get(b.id)
        irr = reference.irrigation()[engine.IRRIGATION_KEYS.get(b.irrigation, b.irrigation)]
        for r in ob.yearly:
            s = bt.seasons[b.id][r.year]
            query = {"parameters": ",".join(power_client.PARAMETERS), "community": "AG", "latitude": lat,
                     "longitude": lon, "start": s.start.strftime("%Y%m%d"), "end": s.end.strftime("%Y%m%d"),
                     "format": "JSON"}
            url = power_client.API_URL + "?" + urlencode(query)
            nasa = f"NASA POWER daily, grid cell {lat:g}, {lon:g}, {s.start} to {s.end}"
            key = f"block.{b.id}.{r.year}"
            fao = "Model estimate from the FAO-56 daily water balance driven by NASA POWER weather"

            rec = Record(f"{key}.crop_water_use_in", f"Crop water use, {name}, {r.year}", "in", 1,
                         "Season crop water use in mm / 25.4 mm per inch", "Inches rounded to 0.1.")
            etc = rec.inp("Season crop water use (sum of daily ET0 x Kc)", rnd(float(s.balance.etc.sum()), 4), "mm",
                          nasa, url, "model", "Model estimate: FAO-56 Penman-Monteith ET0 from NASA POWER x crops.json Kc")
            mm = const(rec, "Millimeters per inch", 25.4, "mm/in", "Definition of the inch", path="backend/simulate.py")
            rec.step("{0} mm / {1} mm per inch", [etc, mm], "{0}/{1}", "in", 1)
            out[rec.id] = rec.out(r.crop_water_use_in)

            rec = Record(f"{key}.effective_rain_in", f"Effective rain, {name}, {r.year}", "in", 1,
                         "Season rain stored in the root zone in mm / 25.4 mm per inch", "Inches rounded to 0.1.")
            rain = rec.inp("Season effective rain stored in the root zone", rnd(float(s.balance.rain_eff.sum()), 4),
                           "mm", nasa, url, "model",
                           "Model estimate: NASA POWER rain, 5 mm/day threshold and 80% rule, limited by soil holding")
            mm = const(rec, "Millimeters per inch", 25.4, "mm/in", "Definition of the inch", path="backend/simulate.py")
            rec.step("{0} mm / {1} mm per inch", [rain, mm], "{0}/{1}", "in", 1)
            out[rec.id] = rec.out(r.effective_rain_in)

            rec = Record(f"{key}.water_applied_af", f"Water applied, {name}, {r.year}", "acre-ft", 1,
                         "Net irrigation mm / 304.8 mm per ft x acres / irrigation efficiency", "Water rounded to 0.1 acre-ft.")
            net = model_input(rec, "Net irrigation applied to the root zone", rnd(s.applied_net_mm, 4), "mm",
                              fao + (", limited by the farm water cap" if s.capped else ""))
            ft = const(rec, "Millimeters per foot", 304.8, "mm/ft", "Definition of the foot", path="backend/simulate.py")
            acres = acres_input(rec, b, req.blocks)
            eff = rec.inp(f"Irrigation efficiency, {b.irrigation.replace('_', ' ')}", irr["efficiency"], "fraction",
                          f"irrigation.json: {irr['source']}", file_url("data/reference/irrigation.json"), "reference",
                          "Placeholder typical efficiency, marked for checking in irrigation.json" if irr.get("verify")
                          else None, "Published efficiency")
            rec.step("{0} mm / {1} mm per ft x {2} acres / {3}", [net, ft, acres, eff], "{0}/{1}*{2}/{3}", "acre-ft", 1)
            out[rec.id] = rec.out(r.water_applied_af)

            rec = Record(f"{key}.relative_yield", f"Percent of full potential, {name}, {r.year}", "%", 1,
                         "Relative yield x 100", "Percent rounded to 0.1.")
            ry = model_input(rec, "Relative yield", r.relative_yield, "fraction",
                             "Model estimate: FAO-33 1 - Ky x (1 - actual ET / full ET), minus a heat-day penalty")
            rec.step("{0} x {1}", [ry, percent_factor(rec)], "{0}*{1}", "%", 1)
            out[rec.id] = rec.out(rnd(r.relative_yield * 100, 1))

            wr = next((x for x in w.yearly if x.year == r.year), None) if w else None
            if wr is not None and wr.tons_per_acre is not None:
                for field, label, d, with_acres in (("tons_per_acre", "Harvest per acre", 3, False),
                                                    ("tons", "Total harvest", 2, True)):
                    unit = "tons" if with_acres else "tons/acre"

                    def build(lb, field=field, label=label, d=d, with_acres=with_acres, unit=unit):
                        rec = Record(f"{key}.{field}", f"{label}, {name}, {r.year}",
                                     unit.replace("tons", "lb") if lb else unit, 0 if lb else d,
                                     "NASS baseline in tons/acre x relative yield / median relative yield"
                                     + (" x acres" if with_acres else "") + (" x 2,000 lb/ton" if lb else ""),
                                     f"Harvest rounded to {'0.01' if with_acres else '0.001'} ton"
                                     + (", then converted exactly to lb." if lb else "."))
                        text, ops, expr = harvest_ops(rec, b, r.relative_yield, typical, ctx, req.blocks, with_acres)
                        t = rec.step(text, ops, expr, unit, d)
                        if lb:
                            rec.step("{0} x {1} lb/ton", [t, lb_per_ton(rec)], "{0}*{1}", unit.replace("tons", "lb"), 0)
                        return rec

                    tons_value = getattr(wr, field)
                    out[f"{key}.{field}"] = build(False).out(tons_value, build(True).out(rnd(tons_value * 2000)))

            rec = Record(f"{key}.heat_stress_days", f"Heat days, {name}, {r.year}", "days", 0,
                         "Growing days with NASA daily maximum temperature above the crop threshold", "Whole days, no rounding.")
            hd = rec.inp(f"Growing days above {params['heat_stress_c']:g} deg C (counted from NASA daily maximum)",
                         s.heat_stress_days, "days", nasa, url, "nasa")
            rec.step("Heat days counted", [hd], "{0}", "days")
            out[rec.id] = rec.out(r.heat_stress_days)

            rec = Record(f"{key}.gdd", f"Growing degree days, {name}, {r.year}", "deg C-days", 0,
                         "Season sum of max(0, (Tmax + Tmin) / 2 - base temperature)", "Rounded to a whole degree day.")
            base_entry = reference.get_crop(b.crop)["gdd_base_c"]
            g = rec.inp(f"Season sum of daily degree days above {params['gdd_base_c']:g} deg C", rnd(s.gdd, 4),
                        "deg C-days", nasa, url, "model",
                        "Computed from NASA daily temperatures with a base temperature still marked for checking"
                        if base_entry.get("verify") else None, "Arithmetic on NASA daily temperatures")
            rec.step("Season sum", [g], "{0}", "deg C-days", 0)
            out[rec.id] = rec.out(r.gdd)

            if r.profit is not None and s.money:
                out[f"{key}.profit"] = profit_record(f"{key}.profit", b, r, s, bt, name, typical)
    return out


def profit_record(rid, b, r, s, bt, name, typical):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    m = s.money
    defaults = engine._price_tables()[2]
    price = m["price"]
    rec = Record(rid, f"Estimated margin, {name}, {r.year}", "$", 0,
                 "Sales (harvest x price) - cost (production + surface water + groundwater pumping)",
                 "Harvest to 0.01 ton, acre-ft to 0.0001, cost parts to $0.01, sales and cost to $1.")
    text, ops, expr = harvest_ops(rec, b, r.relative_yield, typical, ctx, req.blocks, True)
    tons = rec.step("Harvest: " + text, ops, expr, "tons", 2)
    rows = matching_price("data/reference/prices/crop_prices.csv", "crop", b.crop, price)
    filled = req.price_mode == "historical" and price.year != r.year
    sale = m["sale_unit"].lower()
    p = rec.inp(f"{crop_name(b.crop)} price, {price.year}", price.value, f"$/{sale}",
                f"{rows[0]['source'] if rows else 'crop_prices.csv'}, {price.year}",
                file_url("data/reference/prices/crop_prices.csv"), "nass",
                f"Nearest year's price, no NASS price for {r.year}" if filled else None, money=True)
    if m["sale_unit"] == "TON":
        sales = rec.step("Sales: {0} tons x {1} per ton", [tons, p], "{0}*{1}", round_to=0, money=True)
    elif m["sale_unit"] == "LB":
        sales = rec.step("Sales: {0} tons x {1} lb/ton x {2} per lb", [tons, lb_per_ton(rec), p], "{0}*{1}*{2}",
                         round_to=0, money=True)
    else:
        w = const(rec, f"{crop_name(b.crop)} weight per {sale}", economics.unit_to_lb(price.unit, b.crop), f"lb/{sale}",
                  "USDA standard test weight, backend/economics.py BUSHEL_LB", path="backend/economics.py")
        sales = rec.step(f"Sales: {{0}} tons x {{1}} lb/ton / {{2}} lb/{sale} x {{3}} per {sale}",
                         [tons, lb_per_ton(rec), w, p], "{0}*{1}/{2}*{3}", round_to=0, money=True)

    cost = ctx["production_costs"][b.crop]
    warn = ""
    for record in records("data/reference/prices/production_costs.csv"):
        mm = re.search(r"(20[0-9]{2})\.pdf", record["source"])
        if (record["crop"] == b.crop and record["region"] == cost["region"] and mm
                and mm.group(1) != record["study_year"] and record["cost_excl_water"]
                and float(record["cost_excl_water"]) == cost["cost_excl_water"]):
            warn = f"; study year {record['study_year']} differs from the {mm.group(1)} in the file name"
    away = (f"; nearest region with a study ({cost['region']})"
            if ctx.get("cost_region") and ctx["cost_region"] != cost["region"] else "")
    pc = rec.inp("Production cost excluding water", cost["cost_excl_water"], "$/acre", cost["source"],
                 file_url("data/reference/prices/production_costs.csv"), "reference",
                 "Regional reference budget from a UC Davis cost study, not this farm's expenses" + away + warn, money=True)
    acres = N(b.acres)
    parts = [rec.step("Production: {0} per acre x {1} acres", [pc, acres], "{0}*{1}", round_to=2, money=True)]
    water = model_input(rec, "Water applied (to 0.0001 acre-ft)", m["water"], "acre-ft",
                        "Model estimate from the FAO-56 daily water balance")
    share = req.optional.surface_water_share
    sh = share_input(rec, req)
    if share > 0:
        sw = rec.step("Surface water: {0} acre-ft x {1}", [water, sh], "{0}*{1}", "acre-ft", 4)
        parts.append(rec.step("Surface water cost: {0} acre-ft x {1} per acre-ft", [sw, water_price_input(rec, ctx)],
                              "{0}*{1}", round_to=2, money=True))
    if share < 1:
        gs = rec.inp("Groundwater share (1 - surface water share)", m["ground_share"], "fraction",
                     "Rest of the applied water after the surface share", None, "constant",
                     why_not="Complement of the surface water share")
        gw = rec.step("Groundwater: {0} acre-ft x {1}", [water, gs], "{0}*{1}", "acre-ft", 4)
        lift = rec.inp("Well lift", defaults["well_lift_ft"], "ft",
                       f"defaults.json well_lift_ft: {json_defaults()['well_lift_ft'].get('source', '')}",
                       file_url("data/reference/prices/defaults.json"), "reference",
                       f"Default assumption, {defaults['well_lift_ft']:g} ft well lift")
        kwh_ft = const(rec, "Energy to lift 1 acre-ft by 1 ft", economics.KWH_PER_AF_FT, "kWh/(acre-ft x ft)",
                       "backend/economics.py KWH_PER_AF_FT", "Physical constant", "backend/economics.py")
        eff = rec.inp("Pump efficiency", defaults["pump_efficiency"], "fraction", "defaults.json pump_efficiency",
                      file_url("data/reference/prices/defaults.json"), "reference",
                      f"Default assumption, {defaults['pump_efficiency']:.0%} pump efficiency")
        elec = m["elec"]
        erows = matching_price("data/reference/prices/utilities.csv", "type", engine.ELECTRICITY_SERIES, elec)
        cents = economics.normalize_unit(elec.unit) == "CENTS/KWH"
        e = rec.inp(f"Electricity price, {elec.year}", elec.value, "cents/kWh" if cents else "$/kWh",
                    f"{erows[0]['source'] if erows else 'utilities.csv'}, {elec.year}",
                    file_url("data/reference/prices/utilities.csv"), "reference",
                    "California average commercial rate (EIA), not this farm's tariff", money=not cents)
        if cents:
            c100 = const(rec, "Cents per dollar", 100, "cents/$", "Definition of the cent", "Unit conversion")
            e = rec.step("Electricity: {0} cents/kWh / {1} cents per $", [e, c100], "{0}/{1}", "$/kWh")
        parts.append(rec.step("Groundwater cost: {0} acre-ft x {1} ft x {2} kWh / {3} x {4} per kWh",
                              [gw, lift, kwh_ft, eff, N(e.value, True)], "{0}*{1}*{2}/{3}*{4}", round_to=2, money=True))
    total = rec.step("Cost: " + " + ".join("{%d}" % i for i in range(len(parts))), parts,
                     " + ".join("{%d}" % i for i in range(len(parts))), round_to=0, money=True)
    rec.step("Margin: sales {0} - cost {1}", [sales, total], "{0}-{1}", money=True)
    return rec.out(r.profit)


# ---------------------------------------------------------------- data table rows and Average row

def table_series(response, scope, per_acre):
    """{metric: [(year, value or None)]}: the table under a chart, already rounded the way it
    is displayed (frontend/src/features/provenance/chartData.js builds the same rows).

    Totals: harvest to 0.01 ton, dollars to $1, water to 0.1 acre-ft. Per acre: harvest to
    0.001 ton, dollars to $1, water to 0.01 acre-ft. Yield is percent to 0.1. Margin is
    always the shown sales minus the shown cost."""
    weights = {w.block_id: w for w in response.yield_weight}
    rows = {m: [] for m in ("harvest", "sales", "cost", "margin", "water", "yield")}

    def put(y, harvest, sales, cost, water, ry):
        rows["harvest"].append((y, harvest))
        rows["sales"].append((y, sales))
        rows["cost"].append((y, cost))
        rows["margin"].append((y, sales - cost if sales is not None and cost is not None else None))
        rows["water"].append((y, water))
        rows["yield"].append((y, rnd(ry * 100, 1)))

    if scope == "farm":
        total_acres = exact_sum(b.acres for b in response.blocks)
        for t in response.farm_totals:
            known = []
            for b in response.blocks:
                wr = next((r for r in weights[b.id].yearly if r.year == t.year), None) if b.id in weights else None
                if wr is not None and wr.tons is not None:
                    known.append((b.acres, wr.tons))
            h = rnd(exact_sum(v for _, v in known), 2) if known else None  # 0.01-ton values, exact after rounding
            m_acres = exact_sum(b.acres for b in response.blocks
                          if next(r for r in b.yearly if r.year == t.year).profit is not None)
            if per_acre:
                h_acres = exact_sum(a for a, _ in known)
                put(t.year, rnd(h / h_acres, 3) if h is not None else None,
                    rnd(t.revenue / m_acres) if t.revenue is not None else None,
                    rnd(t.cost / m_acres) if t.cost is not None else None,
                    rnd(t.water_applied_af / total_acres, 2), t.relative_yield)
            else:
                put(t.year, h, t.revenue, t.cost, t.water_applied_af, t.relative_yield)
        return rows
    b = next(x for x in response.blocks if x.id == scope)
    w = weights.get(scope)
    for r in b.yearly:
        wr = next((x for x in w.yearly if x.year == r.year), None) if w else None
        if per_acre:
            put(r.year, wr.tons_per_acre if wr else None,
                rnd(r.revenue / b.acres) if r.revenue is not None else None,
                rnd(r.cost / b.acres) if r.cost is not None else None,
                rnd(r.water_applied_af / b.acres, 2), r.relative_yield)
        else:
            put(r.year, wr.tons if wr else None, r.revenue, r.cost, r.water_applied_af, r.relative_yield)
    return rows


TABLE_DECIMALS = {(m, pa): d for m, d_total, d_acre in (
    ("harvest", 2, 3), ("sales", 0, 0), ("cost", 0, 0), ("margin", 0, 0), ("water", 1, 2), ("yield", 1, 1),
    ("margin_pct", 1, 1)) for pa, d in ((False, d_total), (True, d_acre))}
TABLE_UNITS = {"harvest": "tons", "sales": "$", "cost": "$", "margin": "$", "water": "acre-ft", "yield": "%",
               "margin_pct": "%"}
TABLE_REASONS = {"harvest": "Model estimate: NASS median yield scaled by modeled relative yield",
                 "water": "Model estimate from the FAO-56 water balance",
                 "yield": "Model estimate from FAO-33 yield response and FAO-56 water balance"}


def table_average(response, req, scope, per_acre, metric):
    """Average row cell. Returns the record dict, or (tons record, lb record) for harvest,
    or None when the column has no values."""
    series = table_series(response, scope, per_acre)
    b = next((x for x in req.blocks if x.id == scope), None)
    who = "whole farm" if scope == "farm" else block_name(b, req.blocks)
    basis = "per_acre" if per_acre else "total"
    rid = f"table.{scope}.{basis}.{metric}"
    d = TABLE_DECIMALS[(metric, per_acre)]
    unit = TABLE_UNITS[metric] + ("/acre" if per_acre and metric not in ("yield", "margin_pct") else "")
    money = TABLE_UNITS[metric] == "$"
    per = " per acre" if unit.endswith("/acre") else ""
    label = f"Average {METRIC_LABELS[metric]}{per}, {who}"
    rule = {"harvest": f"Harvest rounded to {'0.001' if per_acre else '0.01'} ton.",
            "water": f"Water rounded to {'0.01' if per_acre else '0.1'} acre-ft.",
            "yield": "Percent rounded to 0.1.", "margin_pct": "Percent rounded to 0.1."}.get(metric, ROUND_MONEY)
    reason = TABLE_REASONS.get(metric, MONEY_REASON)

    if metric == "margin_pct":
        avg_s = table_average(response, req, scope, per_acre, "sales")
        avg_m = table_average(response, req, scope, per_acre, "margin")
        if not avg_s or not avg_m or not avg_s["value"]:
            return None
        rec = Record(rid, label, "%", d, "Average margin / average sales x 100", rule)
        mg = model_input(rec, f"Average margin{per}", avg_m["value"], unit.replace("%", "$"), "From the Average row", True)
        sl = model_input(rec, f"Average sales{per}", avg_s["value"], unit.replace("%", "$"), "From the Average row", True)
        v = rec.step("{0} / {1} x {2}", [mg, sl, percent_factor(rec)], "{0}/{1}*{2}", "%", d)
        return rec.out(v.value)
    if metric == "margin":
        sales = [(y, v) for y, v in series["sales"] if v is not None]
        costs = [(y, v) for y, v in series["cost"] if v is not None]
        if not sales or not costs:
            return None
        rec = Record(rid, label, unit, d, f"Average sales{per} - average cost{per}, {years_text([y for y, _ in sales])}",
                     rule + " Averages first, then subtracted.")
        s_ops = yearly_inputs(rec, f"Sales{per}", sales, unit, reason, True)
        c_ops = yearly_inputs(rec, f"Cost{per}", costs, unit, reason, True)
        n = count_input(rec, len(sales))
        sa = rec.step("Average sales: {0} / {1} years", [sum_step(rec, s_ops, money=True, what="yearly sales values"), n],
                      "{0}/{1}", round_to=0, money=True)
        ca = rec.step("Average cost: {0} / {1} years", [sum_step(rec, c_ops, money=True, what="yearly cost values"), n],
                      "{0}/{1}", round_to=0, money=True)
        v = rec.step("Margin: {0} - {1}", [sa, ca], "{0}-{1}", money=True)
        return rec.out(v.value)
    pairs = [(y, v) for y, v in series[metric] if v is not None]
    if not pairs:
        return None
    years = years_text([y for y, _ in pairs])

    def build(lb):
        rec = Record(rid, label, unit.replace("tons", "lb") if lb else unit, 0 if lb else d,
                     f"Sum of the yearly {METRIC_LABELS[metric]}{per} values / number of years with a value, {years}"
                     + (" x 2,000 lb/ton" if lb else ""), rule + (" Pounds to the nearest lb." if lb else ""))
        ops = yearly_inputs(rec, f"{METRIC_LABELS[metric].capitalize()}{per}", pairs,
                            unit if metric != "yield" else "%", reason, money)
        if lb:
            average_steps(rec, ops, 0, unit.replace("tons", "lb"), scale=lb_per_ton(rec))
        else:
            average_steps(rec, ops, d, unit if not money else "", money)
        return rec

    tons_rec = build(False)
    tons_out = tons_rec.out(tons_rec.steps[-1]["result"])
    if metric != "harvest":
        return tons_out
    lb_rec = build(True)
    return tons_out, lb_rec.out(lb_rec.steps[-1]["result"])


def table_records(response, req, ctx):
    out = {}
    for scope in ["farm"] + [b.id for b in response.blocks]:
        for per_acre in (False, True):
            for metric in ("harvest", "sales", "cost", "margin", "water", "yield", "margin_pct"):
                found = table_average(response, req, scope, per_acre, metric)
                if found is None:
                    continue
                if isinstance(found, tuple):
                    found = {**found[0], "lb": found[1]}
                out[found["id"]] = found
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
                         f"Sum of yearly margins of this crop entry / number of years, {yr}", ROUND_MONEY)
            ops = yearly_inputs(rec, f"Margin, {name}", pairs, "$", MONEY_REASON, True)
            average_steps(rec, ops, 0, money=True)
            out[rec.id] = rec.out(rnd(mean(v for _, v in pairs)))
        w = weights.get(b.id)
        if w is not None and w.avg_tons is not None:
            tons = [(r.year, r.tons) for r in w.yearly if r.tons is not None]
            rec = Record(f"block.{b.id}.avg_yield_tons", f"Average harvest, {name}", "tons", 2,
                         f"Sum of yearly harvest of this crop entry / number of years, {yr}",
                         "Harvest rounded to 0.01 ton.")
            ops = yearly_inputs(rec, f"Harvest, {name}", tons, "tons", TABLE_REASONS["harvest"])
            average_steps(rec, ops, 2, "tons")
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
        rec = Record(f"difference.{key}", label, unit, d, "Plan average minus current farm average, per year",
                     ROUND_MONEY if money else f"Rounded to {10 ** -d:g} {unit}.")
        pn = rec.inp("Plan average", p, unit, f"Plan backtest, summary_stats.{key}", file_url("backend/optimize.py"),
                     "model", "Model estimate from the backtest", money=money)
        cn = rec.inp("Current farm average", c, unit, f"Current farm backtest, summary_stats.{key}",
                     file_url("backend/optimize.py"), "model", "Model estimate from the backtest", money=money)
        rec.step("{0} - {1}", [pn, cn], "{0}-{1}", "" if money else unit, d, money)
        out[rec.id] = rec.out(rnd(p - c, d))
    return out
