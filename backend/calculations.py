"""Auditable, year-specific inputs and arithmetic for public backtest results.

Provenance is emitted from the same Backtest used to produce the response. Source
links point to the data publishers (backend/sources.py), never an API key or a
generic claim that NASA supplied production costs.
"""
from __future__ import annotations
import re
from functools import cache
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlencode
import numpy as np
from backend import economics, reference, power_client, sources, yield_weight
from backend.sources import Src, records

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "main"


def source(label, publisher, rows=None):
    """A data set behind the audit, linked to its publisher's page."""
    return {"label": label, "url": sources.LINKS[publisher][1] if publisher else None, "records": rows or []}

def matching_price(path, key, name, price):
    if price is None:
        return []
    return [r for r in records(path) if r[key] == name and int(r["year"]) == price.year]

def cost_breakdown(cost):
    """economics.BlockCost as plain numbers for the audit."""
    if cost is None:
        return None
    line = lambda ln: {"component": ln.component.component, "basis": ln.component.basis, "amount": ln.component.amount,
                       "base_year": ln.component.base_year, "index_name": ln.component.index_name, "ratio": ln.ratio,
                       "region": ln.component.region, "source": ln.component.source, "source_url": ln.component.source_url}
    return {"year_used": cost.year_used, "inputs_per_acre": cost.inputs_per_acre, "inputs": cost.inputs,
            "harvest": cost.harvest, "irrigation_system": cost.irrigation_system, "surface_water": cost.surface,
            "groundwater": cost.groundwater, "weighted_ratio": cost.weighted_ratio,
            "lines": [line(ln) for ln in cost.lines], "system": line(cost.system) if cost.system else None,
            "estimates": cost.estimates}


def build(bt, response, wx):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    prices, _, defaults = engine._price_tables()
    blocks = []
    prepared = engine.prepare_weather(wx)
    for b, out in zip(req.blocks, response.blocks):
        base = ctx["baseline_yields"].get(b.crop)
        typical = median(r.relative_yield for r in out.yearly)
        params = reference.crop_params(b.crop)
        normal = engine.normal_heat_days(b, prepared)
        base_tons = yield_weight.baseline_tons_per_acre(b.crop, ctx) if base else None
        path = "data/validation/ca_county_yields.csv" if base and base["basis"] == "county" else "data/validation/ca_state_yields.csv"
        yield_rows = [r for r in records(path) if r["crop"] == b.crop and (base is None or base["basis"] != "county" or r.get("county") == ctx["county"])] if base else []
        if yield_rows and base and round(median(float(r["yield"]) for r in yield_rows), 3) != base["value"]:
            yield_rows = []  # injected/custom context has no matching committed extract
        comps = engine.cost_components(b.crop, ctx) or []
        cost_rows = [{k: v for k, v in vars(c).items()} for c in comps if c.basis != "excluded"]
        cost_warnings = []
        if yield_rows and max(int(record["year"]) for record in yield_rows) > req.years[1]:
            cost_warnings.append("The baseline yield extract includes reference years after this backtest ends. This is a retrospective scenario using later reference data, not an out-of-sample historical prediction.")
        block_sources = [source("USDA NASS Quick Stats yield records used for the baseline", "nass", yield_rows), {"label": "Cost components used (UC Davis cost study lines, or USDA ERS averages for crops with no California study)", "url": next((c.source_url for c in comps if c.source_url), None), "records": cost_rows}, source("FAO-56 crop coefficients and FAO-66 yield response factors, with verification flags", "fao56", [reference.get_crop(b.crop)]), source("Water and pump default assumptions (not measured)", None, [defaults]), source("Irrigation efficiencies (FAO Training Manual No. 4, placeholders to be checked)", "fao_tm4")]
        yearly = []
        for row in out.yearly:
            s = bt.seasons[b.id][row.year]
            price = engine._lookup_price(prices, b.crop, row.year, req.price_mode, {}, b.crop)
            electricity = (s.money or {}).get("elec")
            active = s.active
            etc, eta = float(s.balance.etc[active].sum()), float(s.balance.eta[active].sum())
            heat_penalty = min(max(s.heat_stress_days-normal, 0)*engine.HEAT_PENALTY_PER_DAY, engine.HEAT_PENALTY_MAX)
            harvest_tpa = base_tons * row.relative_yield / typical if base_tons is not None and typical else None
            m = s.money or {}
            water_cost = m["cost"].water if m else None
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
                "production_cost_excl_water": production_cost,
                "cost_study": {"region": comps[0].region, "base_year": comps[0].base_year, "source_url": comps[0].source_url} if comps else None,
                "source_warnings": cost_warnings, "water_cost": water_cost,
                "applied_water_unrounded_af": s.water_applied_af, "blended_water_price_per_af": bt.water_cost_per_af[row.year],
                "surface_share": req.optional.surface_water_share, "surface_price_per_af": ctx.get("surface_water_price_per_af"),
                "pump_lift_ft": defaults["well_lift_ft"], "pump_efficiency": defaults["pump_efficiency"],
                "electricity_dollars_per_kwh": electricity.value if electricity else None,
                "year_used": m.get("year_used"), "cost_breakdown": cost_breakdown(m.get("cost")),
                "net_irrigation_applied_mm": s.applied_net_mm, "irrigation_efficiency": s.efficiency,
                "etc_active_mm": etc, "eta_active_mm": eta, "etc_all_mm": float(s.balance.etc.sum()), "effective_rain_mm": float(s.balance.rain_eff.sum()),
                "ky": params["ky"], "heat_threshold_c": params["heat_stress_c"], "normal_heat_days": normal,
                "heat_penalty_fraction": heat_penalty, "gdd_base_c": params["gdd_base_c"],
                "kc": params["kc"], "stage_days": params["stage_days"], "soil": req.optional.soil,
                "weather_processing": {"missing_before_fill": {k: int(climate[k].isna().sum()) for k in engine.WEATHER_COLUMNS}, "rule": "Temperature and ET0 gaps are interpolated; missing rain is filled with zero. ET0 is clipped to zero or above."},
                "weather_source": {"label": f"NASA POWER daily input request: {s.start} to {s.end}", "url": power_client.API_URL+"?"+urlencode(query)},
                "price_source": source("USDA NASS Quick Stats price record actually used", "nass", matching_price("data/reference/prices/crop_prices.csv", "crop", b.crop, price)),
                "electricity_source": source("U.S. EIA electricity price record actually used", "eia", [r for r in records(sources.COST_INDEXES) if electricity and r["index_name"] == "electricity" and int(r["year"]) == electricity.year])})
        blocks.append({"id": b.id, "crop": b.crop, "acres": b.acres, "sources": block_sources, "yearly": yearly})
    totals = response.farm_totals
    financial = [r for r in totals if r.profit is not None]
    excluded = [{"block_id": b.id, "crop": b.crop, "years": [r.year for r in b.yearly if r.profit is None]} for b in response.blocks if any(r.profit is None for r in b.yearly)]
    return {"version": 1, "model_revision": BRANCH, "data_revision": BRANCH, "price_mode": req.price_mode,
        "cost_basis": "Regional reference-study estimates plus modeled water cost. No farmer operating expenses were supplied. The budget is a spending limit, not an expense input.",
        "money_basis": "Revenue uses the same median-normalized harvest quantity as the harvest display; costs use a fixed regional study plus modeled water. Dollar results are modeled margins, not observed farm accounts.",
        "validation_status": "Model estimates; source tracing does not establish predictive accuracy. Crop coefficients marked verify=true and pump/water assumptions still require review.",
        "rounding_note": "Calculations use unrounded internal values; crop dollar rows and farm totals are rounded to whole dollars. Displayed rounded inputs may differ slightly when multiplied.",
        "excluded_financial_blocks": excluded,
        "reconciliation": {"avg_revenue": mean(r.revenue for r in financial) if financial else None, "avg_cost": mean(r.cost for r in financial) if financial else None, "avg_profit": mean(r.profit for r in financial) if financial else None, "years": [r.year for r in financial]},
        "annual_totals": [r.model_dump() for r in totals], "blocks": blocks,
        "harvest_source": source("Harvest: USDA NASS median yield scaled by relative yield (FAO-33 Ky on FAO-56 crop water use)", "nass"),
        "weather_record": {"start": str(wx.index.min().date()), "end": str(wx.index.max().date()), "grid_cell": list(bt.grid_cell)}}




# ================================================================ calculation records
# One record per number shown with an information button. A person can redo every
# record by hand from the box alone:
#     {id, label, value, unit, decimals, formula_text, rounding, is_estimate,
#      steps: [{text, expr, result, round}],
#      inputs: [{name, value, unit, source, source_url, links, derived_from, source_verified,
#                kind, is_estimate, estimate_reason, not_estimate_reason}],
#      lb: the same record in pounds (weight records only)}
# Rules (tests/test_hand_calculator.py):
#   * expr uses only + - * / and parentheses on numbers that are input values or
#     earlier step results; every conversion factor and count is an input;
#   * result = expr, rounded half up to `round` decimals when round is set;
#   * the last result equals value, the number the response and the UI show.
# Values from a model (water balance, relative yield) are inputs tagged as estimates.
# Input kinds: farmer, nasa, nass (reported data), reference, constant, model.
# Sources are written for a farmer (backend/sources.py): the data, its publisher, the
# part used and a publisher link; estimates name what they were calculated from.

import re as _re
from backend import units
from backend.rounding import exact_sum, mean, rnd

CROP_NAMES = sources.CROPS
FARMER = Src("Farmer input")
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
        self.parts = None  # cost records: [{name, value, step}] for the four cost parts

    def inp(self, name, value, unit, src, kind="reference", estimate=None, why_not=None, money=False):
        src = src if isinstance(src, Src) else Src(src)
        fields = src.fields()
        season = re.search(r"\.(\d{4})\.", self.id)
        if fields.get("source_year") is None and kind in {"model", "nasa"} and season:
            fields["source_year"] = int(season.group(1))
        self.inputs.append({"name": name, "value": value, "unit": unit, **fields,
                            "kind": kind, "is_estimate": bool(estimate),
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
        if self.parts is not None:
            rec["parts"] = self.parts
        return rec


# ---------------------------------------------------------------- shared inputs

def crop_name(crop):
    return CROP_NAMES.get(crop, crop.replace("_", " "))


def block_name(b, blocks):
    name = crop_name(b.crop)
    return f"{name} {b.id}" if sum(x.crop == b.crop for x in blocks) > 1 else name


def years_text(years):
    return f"{years[0]} to {years[-1]}" if len(years) > 1 else str(years[0])


def model_input(rec, name, value, unit, reason, src, money=False):
    return rec.inp(name, value, unit, src, "model", reason, money=money)


def const(rec, name, value, unit, src, why="Unit conversion"):
    return rec.inp(name, value, unit, src, "constant", why_not=why)


def lb_per_ton(rec):
    return const(rec, "Pounds per ton", 2000, "lb/ton", sources.LB_PER_TON)


def percent_factor(rec):
    return const(rec, "Percent per whole", 100, "%", sources.PERCENT, "Definition of percent")


def count_input(rec, n, what="Years with data"):
    return rec.inp(what, n, "years", "Count of the yearly values listed above", "constant",
                   why_not="Count of listed values")


def acres_input(rec, b, blocks):
    return rec.inp(f"{block_name(b, blocks)} area", b.acres, "acres", FARMER, kind="farmer")


def baseline_input(rec, crop, ctx):
    base = ctx["baseline_yields"][crop]
    county = base["basis"] == "county"
    src = sources.baseline(crop, ctx)
    if not county:
        src.derived_from = src.derived_from or ["USDA NASS California statewide yield"]
    return rec.inp(f"{crop_name(crop)} baseline yield (NASS median)", base["value"],
                   base["unit"].lower().replace(" ", ""), src, "nass",
                   None if county else "Statewide median, not enough county data for this location")


def harvest_ops(rec, b, ry, typical, ctx, blocks, with_acres, season):
    """Inputs and the single expression that turns the NASS baseline into harvest.

    Same order of operations as the harvest weight in the response, so the result is
    exact. season = (grid, start, end, years) of the weather behind this year."""
    grid, start, end, years = season
    params = reference.crop_params(b.crop)
    base = ctx["baseline_yields"][b.crop]
    u = units._normalize(base["unit"])
    v = baseline_input(rec, b.crop, ctx)
    ry_n = model_input(rec, "Relative yield this year", ry, "fraction",
                       "Model estimate from FAO-33 yield response (Ky) and FAO-56 water balance",
                       sources.relative_yield(b.crop, params["ky"], params["heat_stress_c"], grid, start, end))
    typ_n = model_input(rec, "Median relative yield over the backtest years", typical, "fraction",
                        "Model estimate: median of the modeled relative yields",
                        sources.median_relative_yield(b.crop, years))
    if u == units.LB_PER_ACRE:
        ops, text, expr = [v, lb_per_ton(rec)], "{0} lb/acre / {1} lb/ton", "{0}/{1}"
    elif u == units.BU_PER_ACRE:
        lb = units.bushel_weight_lb(b.crop)
        w = const(rec, f"{crop_name(b.crop)} bushel weight", lb, "lb/bu", sources.bushel(b.crop, lb))
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


DEFAULT_SHARE_REASON = ("Default 50/50 surface/well split (team assumption); choose your water source on the form")


def share_input(rec, req):
    share = req.optional.surface_water_share
    if "surface_water_share" in req.optional.model_fields_set:
        return rec.inp("Surface water share", share, "fraction", FARMER, kind="farmer")
    return rec.inp("Surface water share", share, "fraction", sources.surface_share_default(share),
                   "reference", DEFAULT_SHARE_REASON)


def soil_water_inputs(rec, s, grid):
    """Where the season's soil water started and what was left to refill at harvest.
    Shown next to the simulated water applied; they explain it, they are not steps."""
    ss = s.start_soil
    if ss is None:
        return
    if ss.wetness is None:
        rec.inp("Starting soil water, share of what the root zone holds", 1.0, "fraction",
                Src("Full root zone assumed: no NASA POWER GWETPROF value on the planting day", ["nasa"],
                    ["No NASA POWER GWETPROF value for the planting day"]), "model",
                ss.estimate_reason)
    else:
        rec.inp(f"Soil wetness on the planting day, {s.start} (NASA POWER GWETPROF)", ss.wetness,
                "fraction of pore space", sources.soil_wetness(grid, s.start), "nasa",
                why_not="NASA POWER daily value for this grid cell")
        f = reference.soil_water_fractions(ss.soil)
        for key, name in (("porosity", "Total porosity"), ("theta_fc", "Field capacity"),
                          ("theta_wp", "Wilting point")):
            src = sources.soil_property(ss.soil, key)
            rec.inp(f"{name}, {ss.soil}", f[key], "m3/m3", src, "reference",
                    None if src.verified else "Typical value for the soil texture, still to be checked",
                    "Published soil value")
        rec.inp("Starting soil water, share of what the root zone holds", rnd(ss.fraction, 4), "fraction",
                sources.simulation([f"GWETPROF x porosity = {ss.theta:.4f} m3/m3",
                                    "clamp((theta - wilting point) / (field capacity - wilting point), 0, 1)"]),
                "model", "Model estimate from NASA POWER soil wetness and typical soil values")
    rec.inp("Soil water deficit at the end of the season, refilled", rnd(s.balance.end_refill, 4), "mm",
            sources.simulation(["FAO-56 soil water balance on the last day of the season"]), "model",
            "Model estimate: counted as irrigation so water applied does not depend on the last refill date")


def water_price_input(rec, ctx):
    value = ctx.get("surface_water_price_per_af")
    src = sources.water_price(ctx)
    reason = ("Team estimate, no district rate found" if src.text.startswith("Default assumption")
              else "Typical district rate, not this farm's water bill")
    return rec.inp("Surface water price", value, "$/acre-ft", src, "reference", reason, money=True)


def yearly_inputs(rec, name, pairs, unit, reason, src, money=False):
    return [model_input(rec, f"{name}, {y}", v, unit, reason, src, money) for y, v in pairs]


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


def farm_sources(response, req, ctx):
    return sources.Farm(req.blocks, req.price_mode, ctx, response.location.grid_cell, response.years)


def summary_records(response, req, ctx):
    out = {}
    totals = response.farm_totals
    stats = response.summary_stats
    yr = years_text(response.years)
    money_rows = [t for t in totals if t.profit is not None]
    farm = farm_sources(response, req, ctx)

    def money_average(rid, label, field, value):
        pairs = [(t.year, getattr(t, field)) for t in totals if getattr(t, field) is not None]
        if not pairs or value is None:
            return
        word = {"revenue": "sales", "cost": "cost"}[field]
        rec = Record(rid, label, "$", 0, f"Sum of yearly farm {word} / number of years with price data, {yr}",
                     ROUND_MONEY)
        ops = yearly_inputs(rec, f"Farm {word}", pairs, "$", MONEY_REASON, farm.metric(field), True)
        average_steps(rec, ops, 0, money=True)
        out[rid] = rec.out(value)

    if stats is not None and money_rows:
        money_average("summary.avg_cost", "Estimated cost per year", "cost", stats.avg_cost)
        avg_rev = rnd(mean(t.revenue for t in money_rows))
        money_average("summary.avg_revenue", "Estimated sales per year", "revenue", avg_rev)
        rec = Record("summary.avg_profit", "Estimated margin per year", "$", 0,
                     f"Average yearly sales - average yearly cost, {yr}", ROUND_MONEY + " Averages first, then subtracted.")
        s_ops = yearly_inputs(rec, "Farm sales", [(t.year, t.revenue) for t in money_rows], "$", MONEY_REASON,
                              farm.sales(), True)
        c_ops = yearly_inputs(rec, "Farm cost", [(t.year, t.cost) for t in money_rows], "$", MONEY_REASON,
                              farm.cost(), True)
        n = count_input(rec, len(money_rows))
        s_avg = rec.step("Average sales: {0} / {1} years", [sum_step(rec, s_ops, money=True, what="yearly sales values"), n],
                         "{0}/{1}", round_to=0, money=True)
        c_avg = rec.step("Average cost: {0} / {1} years", [sum_step(rec, c_ops, money=True, what="yearly cost values"), n],
                         "{0}/{1}", round_to=0, money=True)
        rec.step("Margin: {0} - {1}", [s_avg, c_avg], "{0}-{1}", money=True)
        out[rec.id] = rec.out(stats.avg_profit)
        rec = Record("summary.total_profit", "Total estimated margin", "$", 0,
                     f"Sum of yearly farm margins (sales - cost), {yr}", ROUND_MONEY)
        ops = yearly_inputs(rec, "Farm margin", [(t.year, t.profit) for t in money_rows], "$", MONEY_REASON,
                            farm.margin(), True)
        sum_step(rec, ops, money=True, what="yearly margins")
        out[rec.id] = rec.out(stats.total_profit)
    if stats is not None and stats.avg_relative_yield is not None:
        rec = Record("summary.avg_relative_yield", "Average relative yield", "%", 1,
                     f"Average of the yearly acre-weighted farm relative yield, x 100, {yr}",
                     "Average rounded to 0.001, then shown as a percent.")
        ops = yearly_inputs(rec, "Farm relative yield", [(t.year, t.relative_yield) for t in totals], "fraction",
                            "Model estimate from FAO-33 yield response and FAO-56 water balance", farm.relative())
        m = average_steps(rec, ops, 3)
        rec.step("{0} x {1}", [m, percent_factor(rec)], "{0}*{1}", "%", 1)
        out[rec.id] = rec.out(rnd(stats.avg_relative_yield * 100, 1))
    if stats is not None and stats.avg_water_applied_af is not None:
        rec = Record("summary.avg_water_applied_af", "Average water per year", "acre-ft", 1,
                     f"Sum of yearly farm water applied / number of years, {yr}", "Water rounded to 0.1 acre-ft.")
        ops = yearly_inputs(rec, "Farm water applied", [(t.year, t.water_applied_af) for t in totals], "acre-ft",
                            "Model estimate from FAO-56 water balance", farm.water())
        average_steps(rec, ops, 1, "acre-ft")
        out[rec.id] = rec.out(stats.avg_water_applied_af)
    if stats is not None and stats.avg_yield_tons is not None:
        found = table_average(response, req, ctx, "farm", False, "harvest")
        if found:
            rec_t, rec_lb = found
            out["summary.avg_yield_tons"] = {**rec_t, "id": "summary.avg_yield_tons",
                                             "label": "Estimated harvest per year",
                                             "lb": {**rec_lb, "id": "summary.avg_yield_tons",
                                                    "label": "Estimated harvest per year"}}
    out.update(ranking_records(response, farm))
    budget = req.optional.budget_usd
    if budget is not None and totals and all(t.cost is not None for t in totals):
        rec = Record("summary.years_over_budget", "Years over budget", "years", 0,
                     "Count of years where estimated farm cost is above the yearly budget",
                     "Whole years, no rounding.")
        b = rec.inp("Yearly operating budget", budget, "$", FARMER, kind="farmer", money=True)
        costs = yearly_inputs(rec, "Farm cost", [(t.year, t.cost) for t in totals], "$", MONEY_REASON,
                              farm.cost(), True)
        over = [(t, c) for t, c in zip(totals, costs) if t.cost > budget]
        for t, c in over:
            rec.step(f"{t.year}: cost {{0}} - budget {{1}}", [c, b], "{0}-{1}", "above the budget", money=True)
        if over:
            one = rec.inp("Each year above the budget counts as", 1, "year", "Counting rule", "constant",
                          why_not="Counting rule")
            rec.step(" + ".join(["{0}"] * len(over)) + " (years above)", [one], "+".join(["{0}"] * len(over)), "years")
        else:
            zero = rec.inp("Years above the budget", 0, "years", "No year's cost is above the budget",
                           "constant", why_not="Count of the listed years")
            rec.step("No year is above the budget", [zero], "{0}", "years")
        out[rec.id] = rec.out(len(over))
    return out


def ranking_records(response, farm):
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
                            "Model estimate from the backtest",
                            farm.margin() if by_profit else farm.relative(), by_profit)
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
        ops = yearly_inputs(rec, "Farm margin", pairs, "$", "Model estimate from the backtest", farm.margin(), True)
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
            grid, start, end = (lat, lon), s.start, s.end
            season = (grid, start, end, response.years)
            key = f"block.{b.id}.{r.year}"
            fao = "Model estimate from the FAO-56 daily water balance driven by NASA POWER weather"

            rec = Record(f"{key}.crop_water_use_in", f"Crop water use, {name}, {r.year}", "in", 1,
                         "Season crop water use in mm / 25.4 mm per inch", "Inches rounded to 0.1.")
            etc = rec.inp("Season crop water use (sum of daily ET0 x Kc)", rnd(float(s.balance.etc.sum()), 4), "mm",
                          sources.crop_water_use(b.crop, grid, start, end), "model",
                          "Model estimate: FAO-56 Penman-Monteith reference ET from NASA POWER x FAO-56 crop coefficient")
            mm = const(rec, "Millimeters per inch", 25.4, "mm/in", sources.MM_PER_IN)
            rec.step("{0} mm / {1} mm per inch", [etc, mm], "{0}/{1}", "in", 1)
            out[rec.id] = rec.out(r.crop_water_use_in)

            rec = Record(f"{key}.effective_rain_in", f"Effective rain, {name}, {r.year}", "in", 1,
                         "Season rain stored in the root zone in mm / 25.4 mm per inch", "Inches rounded to 0.1.")
            rain = rec.inp("Season effective rain stored in the root zone", rnd(float(s.balance.rain_eff.sum()), 4),
                           "mm", sources.effective_rain(grid, start, end, req.optional.soil), "model",
                           "Model estimate: NASA POWER rain, 5 mm/day threshold and 80% rule, limited by soil holding")
            mm = const(rec, "Millimeters per inch", 25.4, "mm/in", sources.MM_PER_IN)
            rec.step("{0} mm / {1} mm per inch", [rain, mm], "{0}/{1}", "in", 1)
            out[rec.id] = rec.out(r.effective_rain_in)

            rec = Record(f"{key}.water_applied_af", f"Water applied, {name}, {r.year}", "acre-ft", 1,
                         "Net irrigation mm / 304.8 mm per ft x acres / irrigation efficiency", "Water rounded to 0.1 acre-ft.")
            net = model_input(rec, "Net irrigation applied to the root zone", rnd(s.applied_net_mm, 4), "mm",
                              fao + (", limited by the farm water cap" if s.capped else ""),
                              sources.net_irrigation(b.crop, grid, start, end, req.optional.soil, s.capped))
            soil_water_inputs(rec, s, grid)
            ft = const(rec, "Millimeters per foot", 304.8, "mm/ft", sources.MM_PER_FT)
            acres = acres_input(rec, b, req.blocks)
            eff = rec.inp(f"Irrigation efficiency, {b.irrigation.replace('_', ' ')}", irr["efficiency"], "fraction",
                          sources.irrigation_efficiency(b.irrigation, irr), "reference",
                          "Placeholder typical efficiency, still to be checked against its source" if irr.get("verify")
                          else None, "Published efficiency")
            rec.step("{0} mm / {1} mm per ft x {2} acres / {3}", [net, ft, acres, eff], "{0}/{1}*{2}/{3}", "acre-ft", 1)
            out[rec.id] = rec.out(r.water_applied_af)

            rec = Record(f"{key}.relative_yield", f"Percent of full potential, {name}, {r.year}", "%", 1,
                         "Relative yield x 100", "Percent rounded to 0.1.")
            ry = model_input(rec, "Relative yield", r.relative_yield, "fraction",
                             "Model estimate: FAO-33 1 - Ky x (1 - actual ET / full ET), minus a heat-day penalty",
                             sources.relative_yield(b.crop, params["ky"], params["heat_stress_c"], grid, start, end))
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
                        text, ops, expr = harvest_ops(rec, b, r.relative_yield, typical, ctx, req.blocks, with_acres,
                                                      season)
                        t = rec.step(text, ops, expr, unit, d)
                        if lb:
                            rec.step("{0} x {1} lb/ton", [t, lb_per_ton(rec)], "{0}*{1}", unit.replace("tons", "lb"), 0)
                        return rec

                    tons_value = getattr(wr, field)
                    out[f"{key}.{field}"] = build(False).out(tons_value, build(True).out(rnd(tons_value * 2000)))

            rec = Record(f"{key}.heat_stress_days", f"Heat days, {name}, {r.year}", "days", 0,
                         "Growing days with NASA daily maximum temperature above the crop threshold", "Whole days, no rounding.")
            hd = rec.inp(f"Growing days above {params['heat_stress_c']:g} deg C (counted from NASA daily maximum)",
                         s.heat_stress_days, "days",
                         sources.heat_days(b.crop, params["heat_stress_c"], grid, start, end), "nasa")
            rec.step("Heat days counted", [hd], "{0}", "days")
            out[rec.id] = rec.out(r.heat_stress_days)

            rec = Record(f"{key}.gdd", f"Growing degree days, {name}, {r.year}", "deg C-days", 0,
                         "Season sum of max(0, (Tmax + Tmin) / 2 - base temperature)", "Rounded to a whole degree day.")
            base_entry = reference.get_crop(b.crop)["gdd_base_c"]
            g = rec.inp(f"Season sum of daily degree days above {params['gdd_base_c']:g} deg C", rnd(s.gdd, 4),
                        "deg C-days", sources.degree_days(b.crop, params["gdd_base_c"], grid, start, end), "model",
                        "Computed from NASA daily temperatures with a base temperature still marked for checking"
                        if base_entry.get("verify") else None, "Arithmetic on NASA daily temperatures")
            rec.step("Season sum", [g], "{0}", "deg C-days", 0)
            out[rec.id] = rec.out(r.gdd)

            if r.profit is not None and s.money:
                out[f"{key}.profit"] = profit_record(f"{key}.profit", b, r, s, bt, name, typical, season)
                out[f"{key}.cost"] = cost_record(f"{key}.cost", b, r, s, bt, name, season)
    return out


def profit_record(rid, b, r, s, bt, name, typical, season):
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    m = s.money
    price = m["price"]
    rec = Record(rid, f"Estimated margin, {name}, {r.year}", "$", 0,
                 "Sales (harvest x price) - cost, where cost = inputs + harvest + water + irrigation system",
                 COST_ROUNDING + " Sales to $1.")
    text, ops, expr = harvest_ops(rec, b, r.relative_yield, typical, ctx, req.blocks, True, season)
    tons = rec.step("Harvest: " + text, ops, expr, "tons", 2)
    filled = req.price_mode == "historical" and price.year != r.year
    sale = m["sale_unit"].lower()
    p = rec.inp(f"{crop_name(b.crop)} price, {price.year}", price.value, f"$/{sale}",
                sources.price(b.crop, price), "nass",
                f"Nearest year's price, no NASS price for {r.year}" if filled else None, money=True)
    if m["sale_unit"] == "TON":
        sales = rec.step("Sales: {0} tons x {1} per ton", [tons, p], "{0}*{1}", round_to=0, money=True)
    elif m["sale_unit"] == "LB":
        sales = rec.step("Sales: {0} tons x {1} lb/ton x {2} per lb", [tons, lb_per_ton(rec), p], "{0}*{1}*{2}",
                         round_to=0, money=True)
    else:
        lb = economics.unit_to_lb(price.unit, b.crop)
        w = const(rec, f"{crop_name(b.crop)} weight per {sale}", lb, f"lb/{sale}", sources.bushel(b.crop, lb))
        sales = rec.step(f"Sales: {{0}} tons x {{1}} lb/ton / {{2}} lb/{sale} x {{3}} per {sale}",
                         [tons, lb_per_ton(rec), w, p], "{0}*{1}/{2}*{3}", round_to=0, money=True)

    total = full_cost_steps(rec, b, s, bt, season, tons)
    rec.step("Margin: sales {0} - cost {1}", [sales, total], "{0}-{1}", money=True)
    return rec.out(r.profit)


COMPONENT_LABELS = {"seed": "Seed", "fertilizer": "Fertilizer", "chemicals": "Chemicals", "labor": "Labor",
                    "machinery_fuel": "Machinery and fuel", "harvest_haul": "Harvest and haul", "other": "Other inputs"}
INDEX_LABELS = {"seeds": "NASS seeds index", "fertilizer": "NASS fertilizer index", "chemicals": "NASS chemicals index",
                "wages": "NASS wage rate index", "fuels": "NASS fuels index", "diesel": "EIA diesel price"}
INDEX_UNITS = {"diesel": "$/gal"}


UCD_REASON = "Typical practice amounts from the UC Davis cost study, not this farm's actual records"
COST_FORMULA = "Cost = inputs + harvest + water + irrigation system"
COST_ROUNDING = ("Harvest to 0.01 ton, index ratios to 0.000001, acre-ft to 0.0001, each cost part to $0.01, "
                 "cost to $1.")
COST_PART_NAMES = ("Inputs", "Harvest", "Water", "Irrigation system")


def cost_steps(rec, b, ctx, m, tons):
    """Steps for economics.block_cost: index ratios, then the inputs, harvest and irrigation
    system parts. Returns {"inputs", "harvest", "system"} steps; water is added by
    full_cost_steps. Mirrors block_cost exactly."""
    cost = m["cost"]
    away = (f"; from the nearest region with a study ({cost.lines[0].component.region})"
            if cost.lines and ctx.get("cost_region") and ctx["cost_region"] != cost.lines[0].component.region else "")
    budget = UCD_REASON + away
    acres = N(b.acres)

    ratios = {}  # (index name, base year) -> step

    def ratio(ln):
        c = ln.component
        key = (c.index_name, c.base_year)
        if key not in ratios:
            label, unit = INDEX_LABELS.get(c.index_name, c.index_name), INDEX_UNITS.get(c.index_name, "index")
            money = c.index_name in INDEX_UNITS
            now = rec.inp(f"{label}, {ln.now.year}", ln.now.value, unit, sources.cost_index(ln.now), "reference",
                          ln.now.estimate_reason, why_not="Published annual value", money=money)
            if ln.base.year == ln.now.year:
                base = now
            else:
                base = rec.inp(f"{label}, {ln.base.year}", ln.base.value, unit, sources.cost_index(ln.base),
                               "reference", ln.base.estimate_reason, why_not="Published annual value", money=money)
            ratios[key] = rec.step(f"{label} ratio, {ln.now.year} / {c.base_year} study year: {{0}} / {{1}}",
                                   [now, base], "{0}/{1}", "", 6)
        return ratios[key]

    amounts = {}

    def amount(c):
        if id(c) not in amounts:
            unit = {"per_acre": "$/acre", "per_ton": "$/ton", "per_acre_system": "$/acre/yr"}[c.basis]
            per = {"per_acre": "per acre", "per_ton": "per ton", "per_acre_system": "per acre per year"}[c.basis]
            name = COMPONENT_LABELS.get(c.component, c.component.replace("_", " ").capitalize())
            if c.basis == "per_acre_system":
                name = f"Irrigation system, {c.component.removeprefix('irrigation_system_').replace('_', '-')}"
            if economics.is_ers(c):
                study, reason = f"USDA ERS U.S. total {c.base_year}", c.estimate_reason
            else:
                study = f"UC Davis {c.region} {c.base_year} study" if c.base_year else "UC Davis study total"
                reason = budget + (f"; {c.estimate_reason}" if c.estimate_reason else "")
            amounts[id(c)] = rec.inp(f"{name} {per}, {study}", c.amount, unit,
                                     sources.cost_component(b.crop, c), "reference", reason, money=True)
        return amounts[id(c)]

    indexed = [ln for ln in cost.lines if ln.now is not None]
    for ln in indexed:
        ratio(ln)
    needs_weighted = any(ln.component.index_name == economics.WEIGHTED_INDEX for ln in cost.lines) or cost.system
    weighted = None
    if needs_weighted and indexed:
        terms = []
        for ln in indexed:
            c = ln.component
            if c.basis == "per_ton":
                y = rec.inp(f"Yield in the UC Davis {c.region} {c.base_year} study", c.study_yield_tpa,
                            "tons/acre", sources.cost_component(b.crop, c), "reference", budget)
                w = rec.step(f"{COMPONENT_LABELS[c.component]} dollars per acre in the study: {{0}} per ton x {{1}} tons",
                             [amount(c), y], "{0}*{1}", "", money=True)
            else:
                w = amount(c)
            terms.append((w, ratios[(c.index_name, c.base_year)]))
        ops = [x for pair in terms for x in pair] + [w for w, _ in terms]
        n = len(terms)
        num = " + ".join("{%d}*{%d}" % (2 * i, 2 * i + 1) for i in range(n))
        den = " + ".join("{%d}" % (2 * n + i) for i in range(n))
        weighted = rec.step("Weighted ratio for costs with no index of their own (other inputs, irrigation system): "
                            f"({num.replace('*', ' x ')}) / ({den})", ops, f"({num})/({den})", "", 6)

    def ratio_of(ln):
        if ln.component.index_name == economics.WEIGHTED_INDEX:
            return weighted
        return ratios[(ln.component.index_name, ln.component.base_year)] if ln.now is not None else None

    per_acre = [ln for ln in cost.lines if ln.component.basis == "per_acre"]
    ops, terms = [], []
    for ln in per_acre:
        a = amount(ln.component)
        r = ratio_of(ln)
        if r is None:
            terms.append("{%d}" % len(ops))
            ops.append(a)
        else:
            terms.append("{%d}*{%d}" % (len(ops), len(ops) + 1))
            ops += [a, r]
    label = ("Inputs per acre (that year's USDA ERS values, not index scaled)"
             if per_acre and all(economics.is_ers(ln.component) for ln in per_acre)
             else "Inputs per acre (each study cost x its index ratio)")
    per = rec.step(label + ": " + " + ".join(
        t.replace("*", " x ") for t in terms), ops, " + ".join(terms), "", 2, money=True)
    out = {"inputs": rec.step("Inputs cost: {0} per acre x {1} acres", [per, acres], "{0}*{1}", round_to=2, money=True)}

    per_ton = [ln for ln in cost.lines if ln.component.basis == "per_ton"]
    if per_ton:
        ln = per_ton[0]
        out["harvest"] = rec.step("Harvest cost: {0} tons x {1} per ton x {2} diesel ratio",
                                  [tons, amount(ln.component), ratio_of(ln)], "{0}*{1}*{2}", round_to=2, money=True)
    else:
        # The study has no separate harvest charge: harvest is in its other lines.
        first = cost.lines[0].component if cost.lines else None
        h = rec.inp("Separate harvest and haul charge per ton", 0, "$/ton", sources.no_harvest_line(b.crop, first),
                    "reference", first.estimate_reason if first is not None and economics.is_ers(first) else budget,
                    money=True)
        out["harvest"] = rec.step("Harvest cost: {0} tons x {1} per ton (no separate harvest line)", [tons, h],
                                  "{0}*{1}", round_to=2, money=True)

    if cost.system is None:
        raise ValueError(f"{b.crop} on {b.irrigation} has no irrigation system cost data")
    c = cost.system.component
    kind = c.component.removeprefix("irrigation_system_").replace("_", "-")
    pieces = economics.system_parts(c)
    if pieces:
        # Yearly system cost = installed cost per acre / system life, for each part in the study.
        reason = budget + (f"; {c.estimate_reason}" if c.estimate_reason else "")
        src = sources.cost_component(b.crop, c)
        ops, terms = [], []
        for line, installed, life in pieces:
            i = rec.inp(f"{line}: installed cost per acre, UC Davis {c.region} {c.base_year} study", installed,
                        "$/acre", src, "reference", reason, money=True)
            n = rec.inp(f"{line}: system life, UC Davis {c.region} {c.base_year} study", life, "years", src,
                        "reference", reason)
            terms.append("{%d}/{%d}" % (len(ops), len(ops) + 1))
            ops += [i, n]
        sy = rec.step(f"Irrigation system ({kind}) per acre per year, installed cost / life: "
                      + " + ".join(t.replace("/", " / ") for t in terms), ops, " + ".join(terms), "", 4, money=True)
        if sy.value != c.amount:
            raise ValueError(f"{sy.value} != {c.amount} for {c.region} {c.component}")
    else:
        sy = amount(c)
    if weighted is None:  # USDA ERS rows: no index scaling
        why = (" (USDA ERS whole-farm average per planted acre already includes these costs; no separate "
               "irrigation system line)" if economics.is_ers(c) else "")
        out["system"] = rec.step(f"Irrigation system cost ({kind}){why}: {{0}} per acre per year x {{1}} acres",
                                 [sy, acres], "{0}*{1}", round_to=2, money=True)
    else:
        out["system"] = rec.step(f"Irrigation system cost ({kind}, installed cost / life): {{0}} per acre per year x "
                                 "{1} weighted ratio x {2} acres", [sy, weighted, acres], "{0}*{1}*{2}",
                                 round_to=2, money=True)
    return out


def full_cost_steps(rec, b, s, bt, season, tons):
    """All cost steps for one block and season: inputs, harvest, water, irrigation system,
    then their sum. Sets rec.parts to the four parts and returns the cost step."""
    from backend import simulate as engine
    req, ctx = bt.request, bt.context
    m = s.money
    defaults = engine._price_tables()[2]
    named = cost_steps(rec, b, ctx, m, tons)

    grid, start, end, _ = season
    irr = reference.irrigation()[engine.IRRIGATION_KEYS.get(b.irrigation, b.irrigation)]
    net = sources.net_irrigation(b.crop, grid, start, end, req.optional.soil, s.capped)
    eff = sources.irrigation_efficiency(b.irrigation, irr)
    water = model_input(rec, "Water applied (to 0.0001 acre-ft)", m["water"], "acre-ft",
                        "Model estimate: simulated irrigation water applied this season",
                        sources.simulation([net.text, eff.text], net.verified and eff.verified))
    soil_water_inputs(rec, s, grid)
    share = req.optional.surface_water_share
    sh = share_input(rec, req)
    water_parts, labels = [], []
    if share > 0:
        sw = rec.step("Surface water: {0} acre-ft x {1}", [water, sh], "{0}*{1}", "acre-ft", 4)
        water_parts.append(rec.step("Surface water cost: {0} acre-ft x {1} per acre-ft",
                                    [sw, water_price_input(rec, ctx)], "{0}*{1}", round_to=2, money=True))
        labels.append("surface water {%d}" % (len(labels)))
    if share < 1:
        gs = rec.inp("Groundwater share (1 - surface water share)", m["ground_share"], "fraction",
                     "Rest of the applied water after the surface share", "constant",
                     why_not="Complement of the surface water share")
        gw = rec.step("Groundwater: {0} acre-ft x {1}", [water, gs], "{0}*{1}", "acre-ft", 4)
        lift = rec.inp("Well lift", defaults["well_lift_ft"], "ft", sources.well_lift(defaults["well_lift_ft"]),
                       "reference", "Team assumption")
        kwh_ft = const(rec, "Energy to lift 1 acre-ft by 1 ft", economics.KWH_PER_AF_FT, "kWh/(acre-ft x ft)",
                       sources.KWH, "Physical constant")
        eff = rec.inp("Pump efficiency", defaults["pump_efficiency"], "fraction",
                      sources.pump_efficiency(defaults["pump_efficiency"]), "reference",
                      f"Default assumption, {defaults['pump_efficiency']:.0%} pump efficiency")
        elec = m["elec"]
        reason = "California average commercial rate (EIA), not this farm's tariff"
        e = rec.inp(f"Electricity price, {elec.year}", elec.value, "$/kWh", sources.electricity(elec), "reference",
                    reason + (f"; {elec.estimate_reason}" if elec.is_estimate else ""), money=True)
        water_parts.append(rec.step("Groundwater pumping cost: {0} acre-ft x {1} ft x {2} kWh / {3} x {4} per kWh",
                                    [gw, lift, kwh_ft, eff, e], "{0}*{1}*{2}/{3}*{4}", round_to=2, money=True))
        labels.append("groundwater pumping {%d}" % (len(labels)))
    expr = " + ".join("{%d}" % i for i in range(len(water_parts)))
    # Each acre-ft comes from one source: the surface share at the district price, the rest pumped.
    source = ("surface water only" if share == 1 else "wells only" if share == 0
              else f"{share:.0%} surface water, {1 - share:.0%} wells")
    water_cost = rec.step(f"Water cost ({source}): " + " + ".join(labels), water_parts, expr,
                          round_to=2, money=True)

    parts = [named["inputs"], named["harvest"], water_cost, named["system"]]
    total = rec.step("Cost: inputs {0} + harvest {1} + water {2} + irrigation system {3}", parts,
                     "{0} + {1} + {2} + {3}", round_to=0, money=True)
    rec.parts = [{"name": n, "value": p.value, "step": f"{n}: {p.text}"} for n, p in zip(COST_PART_NAMES, parts)]
    return total


def cost_record(rid, b, r, s, bt, name, season):
    """Estimated cost of one block in one season, as its four parts."""
    m = s.money
    rec = Record(rid, f"Estimated cost, {name}, {r.year}", "$", 0, COST_FORMULA, COST_ROUNDING)
    acres_input(rec, b, bt.request.blocks)
    tons = model_input(rec, f"{crop_name(b.crop)} harvest this season", m["tons"], "tons",
                       "Model estimate: simulated harvest (baseline yield x relative yield / median x acres)",
                       sources.simulation(["USDA NASS median yield", "Relative yield (FAO-33 Ky, FAO-56 water use)"]))
    full_cost_steps(rec, b, s, bt, season, tons)
    return rec.out(r.cost)


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


def table_average(response, req, ctx, scope, per_acre, metric):
    """Average row cell. Returns the record dict, or (tons record, lb record) for harvest,
    or None when the column has no values."""
    series = table_series(response, scope, per_acre)
    farm = farm_sources(response, req, ctx)
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
        avg_s = table_average(response, req, ctx, scope, per_acre, "sales")
        avg_m = table_average(response, req, ctx, scope, per_acre, "margin")
        if not avg_s or not avg_m or not avg_s["value"]:
            return None
        rec = Record(rid, label, "%", d, "Average margin / average sales x 100", rule)

        def from_row(src, what):
            return Src(f"Average {what} in the Average row of this table. Each year: "
                       + src.text.removeprefix("Calculated each year: "), src.links,
                       [f"Average {what} (Average row)"] + src.derived_from, src.verified)

        mg = model_input(rec, f"Average margin{per}", avg_m["value"], unit.replace("%", "$"), "From the Average row",
                         from_row(farm.margin(scope), "margin"), True)
        sl = model_input(rec, f"Average sales{per}", avg_s["value"], unit.replace("%", "$"), "From the Average row",
                         from_row(farm.sales(scope), "sales"), True)
        v = rec.step("{0} / {1} x {2}", [mg, sl, percent_factor(rec)], "{0}/{1}*{2}", "%", d)
        return rec.out(v.value)
    if metric == "margin":
        sales = [(y, v) for y, v in series["sales"] if v is not None]
        costs = [(y, v) for y, v in series["cost"] if v is not None]
        if not sales or not costs:
            return None
        rec = Record(rid, label, unit, d, f"Average sales{per} - average cost{per}, {years_text([y for y, _ in sales])}",
                     rule + " Averages first, then subtracted.")
        s_ops = yearly_inputs(rec, f"Sales{per}", sales, unit, reason, farm.sales(scope), True)
        c_ops = yearly_inputs(rec, f"Cost{per}", costs, unit, reason, farm.cost(scope), True)
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
                            unit if metric != "yield" else "%", reason, farm.metric(metric, scope), money)
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
                found = table_average(response, req, ctx, scope, per_acre, metric)
                if found is None:
                    continue
                if isinstance(found, tuple):
                    found = {**found[0], "lb": found[1]}
                out[found["id"]] = found
    return out


# ---------------------------------------------------------------- entry points

def table_cost_parts(bt, response, scope, per_acre):
    """Average of the four cost parts over the years with a cost, for the table's Average
    cost box: the same blocks and acres as table_series uses for that scope."""
    blocks = [b for b in response.blocks if scope == "farm" or b.id == scope]
    sums = {n: [] for n in COST_PART_NAMES}
    for y in response.years:
        costs = [bt.seasons[b.id][y].money["cost"] for b in blocks
                 if bt.seasons[b.id][y].money and bt.seasons[b.id][y].cost is not None]
        if not costs:
            continue
        acres = exact_sum(b.acres for b in blocks if bt.seasons[b.id][y].money) if per_acre else 1.0
        for n, attr in zip(COST_PART_NAMES, ("inputs", "harvest", "water", "irrigation_system")):
            sums[n].append(sum(getattr(c, attr) for c in costs) / acres)
    if not sums["Inputs"]:
        return None
    per = " per acre" if per_acre else ""
    return [{"name": n, "value": rnd(sum(v) / len(v)),
             "step": f"Average {n.lower()} cost{per} over {len(v)} years, to $1 (parts can differ from the "
                     "total by $1 after rounding)"} for n, v in sums.items()]


def simulate_records(bt, response, wx):
    req, ctx = bt.request, bt.context
    out = summary_records(response, req, ctx)
    out.update(block_year_records(bt, response, wx))
    out.update(table_records(response, req, ctx))
    for rid, rec in out.items():
        m = re.fullmatch(r"table\.(.+)\.(total|per_acre)\.cost", rid)
        if m:
            parts = table_cost_parts(bt, response, m.group(1), m.group(2) == "per_acre")
            if parts:
                rec["parts"] = parts
    if "summary.avg_cost" in out and "table.farm.total.cost" in out:
        out["summary.avg_cost"]["parts"] = out["table.farm.total.cost"].get("parts")
    return out


def plan_block_records(blocks, resp, ctx):
    """Average margin and harvest of each optimizer plan block."""
    out = {}
    weights = {w.block_id: w for w in resp.yield_weight}
    yr = years_text(resp.years)
    farm = sources.Farm(blocks, None, ctx, resp.location.grid_cell, resp.years)
    for b, ob in zip(blocks, resp.blocks):
        name = block_name(b, blocks)
        pairs = [(r.year, r.profit) for r in ob.yearly if r.profit is not None]
        if pairs:
            rec = Record(f"block.{b.id}.avg_profit", f"Average margin, {name}", "$", 0,
                         f"Sum of yearly margins of this crop entry / number of years, {yr}", ROUND_MONEY)
            ops = yearly_inputs(rec, f"Margin, {name}", pairs, "$", MONEY_REASON, farm.margin(b.id), True)
            average_steps(rec, ops, 0, money=True)
            out[rec.id] = rec.out(rnd(mean(v for _, v in pairs)))
        w = weights.get(b.id)
        if w is not None and w.avg_tons is not None:
            tons = [(r.year, r.tons) for r in w.yearly if r.tons is not None]
            rec = Record(f"block.{b.id}.avg_yield_tons", f"Average harvest, {name}", "tons", 2,
                         f"Sum of yearly harvest of this crop entry / number of years, {yr}",
                         "Harvest rounded to 0.01 ton.")
            ops = yearly_inputs(rec, f"Harvest, {name}", tons, "tons", TABLE_REASONS["harvest"], farm.harvest(b.id))
            average_steps(rec, ops, 2, "tons")
            out[rec.id] = rec.out(w.avg_tons)
    return out


def average_source(who, record):
    """The source of a plan or current-farm average: the yearly values in its own box."""
    yearly = next((i for i in (record or {}).get("inputs", []) if i.get("is_estimate")), None)
    if yearly is None:
        return Src(f"{sources.UNVERIFIED}: the {who} average has no calculation box", ["nasa"],
                   [f"{who.capitalize()} yearly results"], verified=False)
    links = [(link["label"], link["url"]) for link in yearly["links"]]
    return Src(f"Average of the {who}'s yearly results, shown in its own box ({record['label']}). Each year: "
               + yearly["source"].removeprefix("Calculated each year: "), links,
               [f"{who.capitalize()} yearly results"] + yearly["derived_from"], yearly["source_verified"])


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
        pn = rec.inp("Plan average", p, unit, average_source("plan", plan_calcs.get(f"summary.{key}")),
                     "model", "Model estimate from the backtest", money=money)
        cn = rec.inp("Current farm average", c, unit, average_source("current farm", current_calcs.get(f"summary.{key}")),
                     "model", "Model estimate from the backtest", money=money)
        rec.step("{0} - {1}", [pn, cn], "{0}-{1}", "" if money else unit, d, money)
        out[rec.id] = rec.out(rnd(p - c, d))
    return out
