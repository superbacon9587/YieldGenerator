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
from backend import economics, reference, power_client, yield_weight, study_audit

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
        typical = bt.reference_relative_yields.get(b.id, median(r.relative_yield for r in out.yearly))
        params = reference.crop_params(b.crop)
        normal = engine.normal_heat_days(b, prepared)
        base_tons = yield_weight.baseline_tons_per_acre(b.crop, ctx) if base else None
        path = "data/validation/ca_county_yields.csv" if base and base["basis"] == "county" else "data/validation/ca_state_yields.csv"
        yield_rows = [r for r in records(path) if r["crop"] == b.crop and (base is None or base["basis"] != "county" or r.get("county") == ctx["county"])] if base else []
        if yield_rows and base and round(median(float(r["yield"]) for r in yield_rows), 3) != base["value"]:
            yield_rows = []  # injected/custom context has no matching committed extract
        cost_rows = [r for r in records("data/reference/prices/production_costs.csv") if r["crop"] == b.crop and cost and r["region"] == cost["region"] and r["cost_excl_water"] and float(r["cost_excl_water"]) == cost["cost_excl_water"]]
        verified_study = study_audit.match(b.crop, cost)
        cost_warnings = []
        for record in cost_rows:
            filename_year = re.search(r"(20[0-9]{2})\.pdf", record["source"])
            if filename_year and filename_year.group(1) != record["study_year"] and verified_study is None:
                cost_warnings.append(f"Cost record study_year is {record['study_year']} but its cited filename contains {filename_year.group(1)}. This source metadata has not been reconciled; treat this cost as provisional.")
        if yield_rows and max(int(record["year"]) for record in yield_rows) > req.years[1]:
            cost_warnings.append("The baseline yield extract includes reference years after this backtest ends. This is a retrospective scenario using later reference data, not an out-of-sample historical prediction.")
        sources = [source("Baseline yield: exact input extract", path, yield_rows), source("Regional production-cost input extract", "data/reference/prices/production_costs.csv", cost_rows), source("Crop coefficients and their verification flags", "data/reference/crops.json", [reference.get_crop(b.crop)]), source("Water and pump assumptions", "data/reference/prices/defaults.json", [defaults]), source("Irrigation efficiencies", "data/reference/irrigation.json")]
        if verified_study:
            sources.append({"label": f"Verified original UC cost study: {verified_study['cover_year']}, {verified_study['table']}, PDF page {verified_study['pdf_page']}", "url": verified_study['url']+f"#page={verified_study['pdf_page']}", "records": [verified_study]})
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
                "reference_period": [bt.reference_years_used[b.id][0], bt.reference_years_used[b.id][-1]],
                "crop_price": vars(price) if price else None, "electricity_price": vars(electricity) if electricity else None,
                "pounds_per_sale_unit": economics.unit_to_lb(price.unit, b.crop) if price else None,
                "sale_quantity": economics.convert_quantity(harvest_tpa*b.acres, "TON", price.unit, b.crop) if harvest_tpa is not None and price else None,
                "revenue_unrounded": s.revenue, "cost_unrounded": s.cost, "profit_unrounded": s.profit,
                "production_cost_excl_water": production_cost, "production_cost_per_acre": cost["cost_excl_water"] if cost else None,
                "surface_water_cost": s.water_applied_af * req.optional.surface_water_share * ctx["surface_water_price_per_af"] if ctx.get("surface_water_price_per_af") is not None else (0.0 if req.optional.surface_water_share == 0 else None),
                "groundwater_cost": s.water_applied_af * (1-req.optional.surface_water_share) * economics.pumping_cost_per_af(defaults["well_lift_ft"], defaults["pump_efficiency"], electricity.value, electricity.unit) if electricity else (0.0 if req.optional.surface_water_share == 1 else None),
                "verified_cost_study": verified_study,
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
    matched = response.financial_coverage['matched_totals']
    def avg(items, field):
        values=[(getattr(r,field) if hasattr(r,field) else r.get(field)) for r in items]
        values=[v for v in values if v is not None]
        return mean(values) if values else None
    excluded = [{"block_id": b.id, "crop": b.crop, "years": [r.year for r in b.yearly if r.profit is None]} for b in response.blocks if any(r.profit is None for r in b.yearly)]
    return {"version": 1, "model_revision": revision(), "data_revision": revision(), "price_mode": req.price_mode,
        "cost_basis": "Regional study operating costs plus modeled water; cash/non-cash overhead and establishment are not included. No farmer operating expenses were supplied. The budget is a spending limit, not an expense input.",
        "money_basis": "Revenue uses the same median-normalized harvest quantity as the harvest display; costs use a fixed regional study plus modeled water. Dollar results are modeled margins, not observed farm accounts.",
        "validation_status": "Model estimates; source tracing does not establish predictive accuracy. Crop coefficients marked verify=true and pump/water assumptions still require review.",
        "rounding_note": "Calculations use unrounded internal values; crop dollar rows and farm totals are rounded to whole dollars. Displayed rounded inputs may differ slightly when multiplied.",
        "excluded_financial_blocks": excluded,
        "financial_coverage": response.financial_coverage,
        "reconciliation": {"avg_revenue": avg(totals,"revenue"), "avg_cost": avg(totals,"cost"), "avg_profit": avg(totals,"profit"), "matched_avg_revenue": avg(matched,"revenue"), "matched_avg_cost": avg(matched,"cost"), "years": [r.year for r in financial]},
        "annual_totals": [r.model_dump() for r in totals], "blocks": blocks,
        "model_source": source("Exact model implementation", "backend/simulate.py"),
        "harvest_source": source("Harvest conversion and median scaling", "backend/yield_weight.py"),
        "weather_record": {"start": str(wx.index.min().date()), "end": str(wx.index.max().date()), "grid_cell": list(bt.grid_cell)}}
