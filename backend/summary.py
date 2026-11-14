"""Whole-period summary, budget check, land use, and production for /api/simulate.

add_to_response(response, request, context) fills four response fields:

    summary_stats  years_count, total_profit, avg_profit, avg_relative_yield,
                   avg_water_applied_af, avg_cost. Profit and cost use only the
                   years where the farm total has them (a note says so when some
                   years are left out). relative_yield is already area weighted
                   per year in farm_totals; this is the mean over years.
    budget         budget_usd from optional.budget_usd, years_over_budget (farm
                   cost above the budget), max_overrun_usd.
    land           available_acres, peak_acres_in_use, peak_month, and
                   over_capacity_months: for each calendar month, the acres of
                   every block in the ground that month (Nov to Apr wraps), so a
                   winter crop and a summer crop can share the same acres.
    production     per block, yearly relative_yield x baseline_yield x acres in
                   the baseline yield's unit without "/ ACRE" (LB, TONS, BU).
                   Baseline yields come from get_location_context. None when
                   the crop has no baseline yield.

Every value that cannot be computed is None, never 0.
"""

from __future__ import annotations

import re

from backend.schemas import (
    BudgetOut,
    LandOut,
    ProductionOut,
    ProductionYearOut,
    SimulateRequest,
    SimulateResponse,
    SummaryStatsOut,
)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ACRE_EPS = 1e-6


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(x: float | None, digits: int = 0) -> float | None:
    return None if x is None else round(x, digits) + 0.0


# ---------------------------------------------------------------- summary stats

def summary_stats(response: SimulateResponse) -> tuple[SummaryStatsOut, list[str]]:
    totals = response.farm_totals
    profits = [t.profit for t in totals if t.profit is not None]
    costs = [t.cost for t in totals if t.cost is not None]
    notes = []
    if profits and len(profits) < len(totals):
        notes.append(f"Profit totals and averages use the {len(profits)} of {len(totals)} "
                     "years that have price data.")
    stats = SummaryStatsOut(
        years_count=len(totals),
        total_profit=_round(sum(profits)) if profits else None,
        avg_profit=_round(_mean(profits)),
        avg_relative_yield=_round(_mean([t.relative_yield for t in totals]), 3),
        avg_water_applied_af=_round(_mean([t.water_applied_af for t in totals]), 1),
        avg_cost=_round(_mean(costs)),
    )
    return stats, notes


# ---------------------------------------------------------------- budget

def budget(response: SimulateResponse, budget_usd: float | None) -> tuple[BudgetOut, list[str]]:
    if budget_usd is None:
        return BudgetOut(budget_usd=None, years_over_budget=[], max_overrun_usd=None), []
    over = [(t.year, t.cost - budget_usd) for t in response.farm_totals
            if t.cost is not None and t.cost > budget_usd]
    notes = []
    unknown = [t.year for t in response.farm_totals if t.cost is None]
    if unknown:
        notes.append(f"Budget could not be checked in {len(unknown)} years with no cost data.")
    partial = any(y.cost is None for b in response.blocks for y in b.yearly)
    if partial and len(unknown) < len(response.farm_totals):
        notes.append("Budget check uses farm cost from blocks with price data only, so the "
                     "real total may be higher.")
    return BudgetOut(
        budget_usd=budget_usd,
        years_over_budget=[y for y, _ in over],
        max_overrun_usd=_round(max(o for _, o in over)) if over else None,
    ), notes


# ---------------------------------------------------------------- land

def monthly_acres(request: SimulateRequest) -> list[float]:
    """Acres in the ground for each calendar month, January first."""
    acres = [0.0] * 12
    for b in request.blocks:
        for m in b.months:
            acres[m - 1] += b.acres
    return acres


def land(request: SimulateRequest) -> tuple[LandOut, list[str]]:
    available = float(request.available_acres)
    acres = monthly_acres(request)
    peak = max(acres)
    peak_index = acres.index(peak)
    over = [MONTH_NAMES[i] for i, a in enumerate(acres) if a > available + ACRE_EPS]
    notes = []
    if over:
        notes.append(f"Crops in the ground exceed the {available:,.1f} available acres in "
                     f"{', '.join(over)} (peak {peak:,.1f} acres). Results still run as entered.")
    return LandOut(
        available_acres=round(available, 2),
        peak_acres_in_use=round(peak, 2),
        peak_month=MONTH_NAMES[peak_index],
        over_capacity_months=over,
    ), notes


# ---------------------------------------------------------------- production

def production_unit(unit: str) -> str:
    """'LB / ACRE' -> 'LB', 'TONS / ACRE' -> 'TONS', 'BU/ACRE' -> 'BU'."""
    return re.sub(r"\s*/\s*AC(RE)?\s*$", "", unit.strip(), flags=re.IGNORECASE).strip()


def production(response: SimulateResponse, context: dict) -> list[ProductionOut]:
    baselines = context.get("baseline_yields", {}) or {}
    out = []
    for b in response.blocks:
        base = baselines.get(b.crop)
        unit = production_unit(base["unit"]) if base else None
        digits = 0 if unit and unit.upper().startswith("LB") else 1
        out.append(ProductionOut(
            block_id=b.id,
            crop=b.crop,
            unit=unit,
            yearly=[ProductionYearOut(
                year=y.year,
                value=(_round(y.relative_yield * base["value"] * b.acres, digits)
                       if base else None))
                for y in b.yearly],
        ))
    return out


# ---------------------------------------------------------------- hook

def add_to_response(response: SimulateResponse, request: SimulateRequest,
                    context: dict) -> SimulateResponse:
    stats, n1 = summary_stats(response)
    bud, n2 = budget(response, request.optional.budget_usd)
    lnd, n3 = land(request)
    response.summary_stats = stats
    response.budget = bud
    response.land = lnd
    response.production = production(response, context)
    response.assumptions.extend(n1 + n2 + n3)
    return response
