"""Farm plan optimizer for POST /api/optimize (Part C, iteration 2).

Main entry point:
    optimize(request, wx=None, context=None)  -> OptimizeResponse

Steps:
 1. Options. Every allowed (crop, irrigation, start_month). A perennial has one
    option per irrigation type, year-round (1 to 12). An annual has one option
    per month in crops.json planting_months; it stays in the field for
    round(season_days / 30.44) whole months (5 for every annual today), so the
    end month wraps past December when needed (oats planted in October end in
    February). Annuals without planting_months are skipped, never guessed.
 2. Per acre results. Each option runs through the existing engine
    (simulate.run_backtest and simulate.apply_money) for exactly 1 acre, over
    the backtest years, with no farm water limit. Per year it records gross
    water applied, relative yield, tons per acre (backend/units.py through the
    shared yield_weight scaling), revenue, revenue at current prices, and total
    cost including water (surface and groundwater split as in /api/simulate),
    plus the months the land is occupied. Results are cached per option. There
    is no second water or yield model: without a water limit the engine is
    linear in acres, so a plan's totals are acre-weighted sums.
 3. Mixed integer linear program (scipy.optimize.milp, HiGHS). Acres are whole
    multiples of 0.1 (x_o = 0.1 k_o, k_o integer), so the solver's answer is the
    plan with no rounding afterward. A binary y_o per option gives
    min_block_acres y_o <= x_o <= available_acres y_o. Constraints:
        land      each month: acres of options in the ground <= available_acres
        budget    every_year: each year's cost <= budget_usd; average: mean <= it
        water     each year: water applied <= water_available_af, so crops are
                  never planned into a shortage and per acre yields stay valid
        share     each crop: its acres <= max_share_per_crop x available_acres
        locked    allow_new_perennials false: each perennial's acres equal its
                  current_farm acres (irrigation may change); other perennials 0
    Objectives: profit (average revenue minus average cost), production_value
    (average revenue at current prices whatever price_mode is, so crops are
    comparable; raw tons are never maximized), profit_per_af (average profit /
    average water, solved exactly with Dinkelbach iterations, then the most
    profit at that ratio). Ties prefer less water.
 4. Verify. The plan runs through the full simulate.simulate path with the
    request's budget, water limit, and land. Profit, water, and cost must match
    the optimizer within 1 percent (or the engine's whole dollar and 0.1 acre-ft
    rounding), and no land, budget, water, share, or locked acre limit may be
    broken in any year. Otherwise the status is "error" with details.
 5. Explain. Binding limits become plain sentences. Infeasible requests get a
    plain English reason.
 6. Alternatives. Up to 3 more plans, each re-solved with a no-good cut that
    forbids the exact set of options already used, labeled "Alternative 1" to 3.
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import get_args

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from backend import reference, simulate as engine, units, yield_weight
from backend.schemas import (
    PERENNIALS,
    BlockIn,
    Crop,
    Irrigation,
    LocationContext,
    OptimizeAlternativeOut,
    OptimizeBlockOut,
    OptimizeCurrentFarmOut,
    OptimizeDifferenceOut,
    OptimizePlanOut,
    OptimizeRequest,
    OptimizeResponse,
    OptionalIn,
    SimulateRequest,
    SimulateResponse,
)
from backend.summary import MONTH_NAMES

DAYS_PER_MONTH = 365.25 / 12
ACRE_STEP = 0.1                 # acres are whole multiples of this
STEPS_PER_ACRE = 10
SOLVER_TIME_LIMIT_S = 20.0
SOLVER_GAP = 1e-9
MAX_ALTERNATIVES = 3
MAX_ALTERNATIVE_SOLVES = 12     # cuts tried while looking for distinct alternatives
DINKELBACH_MAX_ITER = 50
MATCH_REL_TOL = 0.01            # verification: optimizer vs engine within 1 percent
BINDING_REL_TOL = 1e-6
CACHE_SIZE = 4096

PERENNIAL_LAG_NOTE = "New orchards take 3 to 5 years to bear; establishment costs are not modeled."
ZERO_WATER_NOTE = ("Some options need no irrigation water in these years, so their profit per "
                   "acre-foot has no upper limit; the plan uses only options that apply no water.")


# ---------------------------------------------------------------- options

@dataclass(frozen=True)
class OptionKey:
    crop: str
    irrigation: str
    start_month: int
    end_month: int


@dataclass
class Option:
    """Per acre engine results for one option, one value per backtest year."""
    key: OptionKey
    months: tuple[int, ...]
    water: np.ndarray             # gross acre-ft per acre
    relative_yield: np.ndarray
    tons: np.ndarray | None       # US tons per acre; None without a baseline yield
    revenue: np.ndarray           # $ per acre at the request's price mode
    revenue_current: np.ndarray   # $ per acre at current prices
    cost: np.ndarray              # $ per acre, production plus water

    @property
    def crop(self) -> str:
        return self.key.crop

    @property
    def profit(self) -> np.ndarray:
        return self.revenue - self.cost

    def block(self, block_id: str, acres: float) -> BlockIn:
        k = self.key
        return BlockIn(id=block_id, crop=k.crop, acres=acres, irrigation=k.irrigation,
                       start_month=k.start_month, end_month=k.end_month)


def season_months(crop: str) -> int | None:
    """Whole months an annual is in the field, from season_days. None for perennials."""
    days = reference.season_days(crop)
    if crop in PERENNIALS or not days:
        return None
    return max(1, min(12, round(days / DAYS_PER_MONTH)))


def planting_windows(crop: str) -> list[tuple[int, int]]:
    """(start_month, end_month) pairs for a crop. The end month wraps past December."""
    if crop in PERENNIALS:
        return [(1, 12)]
    months = reference.planting_months(crop)
    n = season_months(crop)
    if not months or not n:
        return []
    return [(m, (m + n - 2) % 12 + 1) for m in sorted(set(months))]


def _weather_covers(block: BlockIn, years: list[int], wx: pd.DataFrame) -> bool:
    for y in years:
        start, end = engine.season_dates(block, y)
        if len(wx.loc[str(start): str(end)]) != (end - start).days + 1:
            return False
    return True


# Per option results, keyed by everything that can change them. Values are an
# Option or a string saying why the option has no complete money data.
_CACHE: OrderedDict[tuple, Option | str] = OrderedDict()


def _common_key(req: OptimizeRequest, wx: pd.DataFrame, ctx: dict) -> tuple:
    fingerprint = int(pd.util.hash_pandas_object(wx, index=True).sum())
    return (req.location.lat, req.location.lon, tuple(req.years), req.price_mode, req.soil,
            fingerprint, json.dumps(ctx, sort_keys=True, default=str))


def _crop_label(crop: str) -> str:
    return crop.replace("_", " ").capitalize()


def _crop_noun(crop: str) -> str:
    return {"almonds": "almond", "walnuts": "walnut", "alfalfa_hay": "alfalfa",
            "processing_tomatoes": "processing tomato", "oats": "oat"}.get(crop, crop)


def _missing_money_reason(crop: str, ctx: dict) -> str:
    missing = [name for name, table in (("baseline yield", "baseline_yields"),
                                        ("production cost", "production_costs"))
               if crop not in ctx[table]]
    what = " or ".join(missing) if missing else "crop or water price for some years"
    return (f"{_crop_label(crop)} was left out: it has no {what} for this location, so its "
            "profit and cost cannot be checked.")


def _base_tons_per_acre(crop: str, ctx: dict) -> float | None:
    base = ctx["baseline_yields"].get(crop)
    if not base:
        return None
    try:
        return units.to_tons_per_acre(base["value"], base["unit"], crop)
    except units.UnknownUnitError:
        return None


def evaluate_options(req: OptimizeRequest, keys: list[OptionKey], wx: pd.DataFrame,
                     ctx: dict) -> dict[OptionKey, Option | str]:
    """Engine results per acre for each key, from the cache when possible."""
    common = _common_key(req, wx, ctx)
    out: dict[OptionKey, Option | str] = {}
    todo = []
    for key in keys:
        hit = _CACHE.get((common, key))
        if hit is None:
            todo.append(key)
        else:
            _CACHE.move_to_end((common, key))
            out[key] = hit
    if not todo:
        return out

    years = list(range(req.years[0], req.years[1] + 1))
    blocks = [BlockIn(id=f"o{i + 1}", crop=k.crop, acres=1.0, irrigation=k.irrigation,
                      start_month=k.start_month, end_month=k.end_month)
              for i, k in enumerate(todo)]
    sim = SimulateRequest(location=req.location, years=req.years, price_mode=req.price_mode,
                          blocks=blocks, optional=OptionalIn(soil=req.soil))
    bt = engine.run_backtest(sim, wx)
    bt.context = ctx
    engine.apply_money(bt, ctx)
    money = {b.id: [(bt.seasons[b.id][y].revenue, bt.seasons[b.id][y].cost) for y in years]
             for b in blocks}
    if req.price_mode == "current":
        current = {b.id: [r for r, _ in money[b.id]] for b in blocks}
    else:  # production value always uses current prices
        bt_now = replace(bt, request=sim.model_copy(update={"price_mode": "current"}),
                         water_cost_per_af={}, money_notes=[])
        engine.apply_money(bt_now, ctx)
        current = {b.id: [bt.seasons[b.id][y].revenue for y in years] for b in blocks}

    for key, b in zip(todo, blocks):
        rows = money[b.id]
        if any(r is None or c is None for r, c in rows) or any(r is None for r in current[b.id]):
            result: Option | str = _missing_money_reason(key.crop, ctx)
        else:
            seasons = [bt.seasons[b.id][y] for y in years]
            ry = [s.relative_yield for s in seasons]
            tons = yield_weight.scale_to_tons(_base_tons_per_acre(key.crop, ctx), ry)
            result = Option(
                key=key, months=tuple(b.months),
                water=np.array([s.water_applied_af for s in seasons]),
                relative_yield=np.array(ry),
                tons=None if tons[0] is None else np.array(tons, dtype=float),
                revenue=np.array([r for r, _ in rows]),
                revenue_current=np.array(current[b.id], dtype=float),
                cost=np.array([c for _, c in rows]),
            )
        out[key] = result
        _CACHE[(common, key)] = result
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)
    return out


# ---------------------------------------------------------------- problem

@dataclass
class Problem:
    request: OptimizeRequest
    years: list[int]
    options: list[Option]
    locked: dict[str, float] = field(default_factory=dict)      # crop -> acres (0.1 steps)
    lock_errors: list[str] = field(default_factory=list)
    notes: dict[str, None] = field(default_factory=dict)        # ordered set
    excluded: dict[str, None] = field(default_factory=dict)

    @property
    def budget_limit(self) -> float:
        """Budget less the engine's whole dollar rounding (half a dollar per block plus one)."""
        return self.request.budget_usd - 0.5 * (len(self.options) + 1)

    @property
    def water_limit(self) -> float | None:
        cap = self.request.water_available_af
        return None if cap is None else cap - 1e-6 * max(1.0, cap)


def build_problem(req: OptimizeRequest, wx: pd.DataFrame, ctx: dict) -> Problem:
    years = list(range(req.years[0], req.years[1] + 1))
    crops = list(dict.fromkeys(req.allowed_crops or get_args(Crop)))
    irrigations = list(dict.fromkeys(req.allowed_irrigation or get_args(Irrigation)))
    problem = Problem(req, years, [])

    if not req.allow_new_perennials:
        current = req.current_farm.blocks if req.current_farm else []
        for crop in dict.fromkeys(b.crop for b in current if b.crop in PERENNIALS):
            acres = sum(b.acres for b in current if b.crop == crop)
            stepped = round(acres * STEPS_PER_ACRE) / STEPS_PER_ACRE
            problem.locked[crop] = stepped
            if abs(stepped - acres) > 1e-9:
                problem.notes[f"{_crop_label(crop)} acres are fixed at {stepped:g}, the current "
                              f"{acres:g} acres rounded to {ACRE_STEP:g} acre."] = None
            if crop not in crops:
                problem.lock_errors.append(
                    f"The current {acres:g} {_crop_noun(crop)} acres are locked, but "
                    f"{_crop_noun(crop)}s are not in the allowed crops.")

    keys = []
    for crop in crops:
        if crop in PERENNIALS and not req.allow_new_perennials and crop not in problem.locked:
            problem.excluded[f"{_crop_label(crop)} was left out: new perennial plantings are off "
                             "and the current farm does not grow it."] = None
            continue
        windows = planting_windows(crop)
        if not windows:
            problem.excluded[f"{_crop_label(crop)} was left out: crops.json has no planting "
                             "months for it."] = None
        for start, end in windows:
            for irr in irrigations:
                block = BlockIn(id="x", crop=crop, acres=1.0, irrigation=irr,
                                start_month=start, end_month=end)
                if _weather_covers(block, years, wx):
                    keys.append(OptionKey(crop, irr, start, end))
                else:
                    problem.excluded[
                        f"{_crop_label(crop)} planted in {MONTH_NAMES[start - 1]} was left out: "
                        "its seasons need weather outside the available record."] = None

    for key, result in evaluate_options(req, keys, wx, ctx).items():
        if isinstance(result, str):
            problem.excluded[result] = None
        else:
            problem.options.append(result)

    for crop, acres in problem.locked.items():
        if crop in crops and not any(o.crop == crop for o in problem.options):
            why = " ".join(e for e in problem.excluded if e.startswith(_crop_label(crop)))
            problem.lock_errors.append(
                f"The current {acres:g} {_crop_noun(crop)} acres are locked, but no "
                f"{_crop_noun(crop)} option can be used. " + (why or "No irrigation type is allowed."))
    return problem


# ---------------------------------------------------------------- constraints and solving

@dataclass
class Row:
    kind: str                    # land, share, locked, budget, water, cut, keep
    label: object
    coeffs: np.ndarray           # per acre (per binary y for "cut")
    lb: float
    ub: float


def constraint_rows(problem: Problem) -> list[Row]:
    req, opts = problem.request, problem.options
    rows: list[Row] = []
    for m in range(1, 13):
        coeffs = np.array([1.0 if m in o.months else 0.0 for o in opts])
        if coeffs.any():
            rows.append(Row("land", m, coeffs, -np.inf, req.available_acres))
    for crop in dict.fromkeys(o.crop for o in opts):
        coeffs = np.array([1.0 if o.crop == crop else 0.0 for o in opts])
        rows.append(Row("share", crop, coeffs, -np.inf, req.max_share_per_crop * req.available_acres))
        if crop in problem.locked:
            rows.append(Row("locked", crop, coeffs, problem.locked[crop], problem.locked[crop]))
    cost = np.array([o.cost for o in opts])
    if req.budget_rule == "every_year":
        rows += [Row("budget", y, cost[:, j], -np.inf, problem.budget_limit)
                 for j, y in enumerate(problem.years)]
    else:
        rows.append(Row("budget", None, cost.mean(axis=1), -np.inf, problem.budget_limit))
    if problem.water_limit is not None:
        water = np.array([o.water for o in opts])
        rows += [Row("water", y, water[:, j], -np.inf, problem.water_limit)
                 for j, y in enumerate(problem.years)]
    return rows


def no_good_cut(problem: Problem, used: set[int]) -> Row:
    """Forbid exactly this set of options: sum(y in set) - sum(y not in set) <= |set| - 1."""
    coeffs = np.array([1.0 if i in used else -1.0 for i in range(len(problem.options))])
    return Row("cut", None, coeffs, -np.inf, len(used) - 1)


def solve_milp(problem: Problem, objective: np.ndarray, rows: list[Row]
               ) -> tuple[np.ndarray | None, str]:
    """Maximize objective @ acres. Returns (acres, "optimal" | "feasible") or (None, message)."""
    n = len(problem.options)
    req = problem.request
    k_max = math.floor(req.available_acres * STEPS_PER_ACRE + 1e-9)
    k_min = max(math.ceil(req.min_block_acres * STEPS_PER_ACRE - 1e-9), 1)
    a_rows, lbs, ubs = [], [], []
    for r in rows:
        if r.kind == "cut":
            a_rows.append(np.concatenate([np.zeros(n), r.coeffs]))
        else:  # acres = k / STEPS_PER_ACRE
            a_rows.append(np.concatenate([r.coeffs / STEPS_PER_ACRE, np.zeros(n)]))
        lbs.append(r.lb)
        ubs.append(r.ub)
    for i in range(n):  # k_min y_i <= k_i <= k_max y_i
        hi, lo = np.zeros(2 * n), np.zeros(2 * n)
        hi[i], hi[n + i] = 1.0, -k_max
        lo[i], lo[n + i] = 1.0, -k_min
        a_rows += [hi, lo]
        lbs += [-np.inf, 0.0]
        ubs += [0.0, np.inf]
    usable = 1.0 if k_min <= k_max else 0.0
    res = milp(
        c=np.concatenate([-objective / STEPS_PER_ACRE, np.zeros(n)]),
        integrality=np.ones(2 * n),
        bounds=Bounds(np.zeros(2 * n), np.concatenate([np.full(n, k_max * usable),
                                                        np.full(n, usable)])),
        constraints=LinearConstraint(np.array(a_rows), lbs, ubs),
        options={"time_limit": SOLVER_TIME_LIMIT_S, "mip_rel_gap": SOLVER_GAP},
    )
    if res.x is None:
        return None, res.message
    acres = np.round(res.x[:n]) / STEPS_PER_ACRE
    return acres, ("optimal" if res.status == 0 else "feasible")


def _tiebreak(values: np.ndarray, prefer_less: np.ndarray) -> np.ndarray:
    """Tiny penalty on prefer_less, at most a millionth of the objective scale."""
    scale = float(np.abs(values).max()) if len(values) else 0.0
    top = float(np.abs(prefer_less).max()) if len(prefer_less) else 0.0
    if scale == 0 or top == 0:
        return values
    return values - 1e-6 * scale / top * prefer_less


def per_acre_means(problem: Problem) -> dict[str, np.ndarray]:
    opts = problem.options
    return {
        "profit": np.array([o.profit.mean() for o in opts]),
        "production_value": np.array([o.revenue_current.mean() for o in opts]),
        "cost": np.array([o.cost.mean() for o in opts]),
        "water": np.array([o.water.mean() for o in opts]),
    }


@dataclass
class Solution:
    acres: np.ndarray
    status: str
    rows: list[Row]
    objective_value: float


def solve(problem: Problem, objective: str, extra: list[Row] | None = None) -> Solution | None:
    means = per_acre_means(problem)
    rows = constraint_rows(problem) + (extra or [])
    p, w = means["profit"], means["water"]

    if objective in ("profit", "production_value"):
        acres, status = solve_milp(problem, _tiebreak(means[objective], w), rows)
        if acres is None:
            return None
        return Solution(acres, status, rows, float(means[objective] @ acres))

    # profit_per_af, Dinkelbach: F(lam) = max (p - lam w) @ x. The best ratio is where F = 0.
    acres, status = solve_milp(problem, _tiebreak(p, w), rows)
    if acres is None:
        return None
    if p @ acres <= 0 or w @ acres <= 1e-9:
        ratio = math.inf if p @ acres > 0 else float(p @ acres) / max(float(w @ acres), 1e-9)
        return Solution(acres, status, rows, ratio)
    lam = float(p @ acres) / float(w @ acres)
    tol = 1e-9 * max(1.0, abs(float(p @ acres)))
    for _ in range(DINKELBACH_MAX_ITER):
        trial, trial_status = solve_milp(problem, p - lam * w, rows)
        if trial is None or (p - lam * w) @ trial <= tol:
            break
        if w @ trial <= 1e-9:  # profitable with no irrigation water: unlimited ratio
            dry = Row("keep", "no_water", w, -np.inf, 1e-9)
            best, best_status = solve_milp(problem, _tiebreak(p, w), rows + [dry])
            if best is not None and p @ best > 0:
                problem.notes[ZERO_WATER_NOTE] = None
                return Solution(best, best_status, rows, math.inf)
            break
        acres, status = trial, trial_status
        lam = float(p @ acres) / float(w @ acres)
    # Most profit among plans with the best ratio.
    keep = Row("keep", "ratio", p - lam * w, -tol, np.inf)
    best, best_status = solve_milp(problem, _tiebreak(p, w), rows + [keep])
    if best is not None and w @ best > 1e-9:
        acres, status = best, best_status
    return Solution(acres, status, rows, float(p @ acres) / float(w @ acres))


# ---------------------------------------------------------------- engine check

def run_engine(req: OptimizeRequest, blocks: list[BlockIn], wx, ctx: dict) -> SimulateResponse:
    sim = SimulateRequest(
        location=req.location, years=req.years, price_mode=req.price_mode,
        blocks=[BlockIn(**b.model_dump(include=set(BlockIn.model_fields))) for b in blocks],
        optional=OptionalIn(soil=req.soil, water_available_af=req.water_available_af,
                            budget_usd=req.budget_usd),
        available_acres=req.available_acres)
    return engine.simulate(sim, wx=wx, context=ctx, include_comparisons=False)


def plan_blocks(problem: Problem, acres: np.ndarray) -> list[BlockIn]:
    picks = [(o, round(float(a), 1)) for o, a in zip(problem.options, acres) if a > 0]
    picks.sort(key=lambda p: (p[0].crop not in PERENNIALS, p[0].key.start_month, p[0].crop,
                              p[0].key.irrigation))
    return [o.block(f"p{i + 1}", a) for i, (o, a) in enumerate(picks)]


def blocks_out(blocks: list[BlockIn], resp: SimulateResponse) -> list[OptimizeBlockOut]:
    weights = {w.block_id: w for w in resp.yield_weight}
    out = []
    for b, result in zip(blocks, resp.blocks):
        profits = [y.profit for y in result.yearly if y.profit is not None]
        w = weights.get(b.id)
        out.append(OptimizeBlockOut(
            **b.model_dump(include=set(BlockIn.model_fields)),
            avg_profit=round(sum(profits) / len(profits)) if profits else None,
            avg_yield_tons=w.avg_tons if w else None))
    return out


def _close(engine_value: float | None, predicted: float, abs_tol: float) -> bool:
    if engine_value is None:
        return False
    return abs(engine_value - predicted) <= max(MATCH_REL_TOL * abs(predicted), abs_tol)


def predicted_totals(problem: Problem, acres: np.ndarray) -> dict[str, float]:
    means = per_acre_means(problem)
    return {k: float(means[k] @ acres) for k in ("profit", "cost", "water")}


def verify(problem: Problem, acres: np.ndarray, blocks: list[BlockIn],
           resp: SimulateResponse) -> list[str]:
    """Problems found when the plan runs through the full /api/simulate path."""
    req = problem.request
    stats, n = resp.summary_stats, len(blocks)
    predicted = predicted_totals(problem, acres)
    issues = []
    for name, value, abs_tol in (("profit", stats.avg_profit, n + 1.0),
                                 ("cost", stats.avg_cost, n + 1.0),
                                 ("water", stats.avg_water_applied_af, 0.15)):
        if not _close(value, predicted[name], abs_tol):
            issues.append(f"Average {name} from the engine ({value}) differs from the "
                          f"optimizer ({predicted[name]:,.2f}) by more than 1 percent.")
    if req.budget_rule == "every_year":
        over = [t.year for t in resp.farm_totals if t.cost is None or t.cost > req.budget_usd]
        if over:
            issues.append(f"Farm cost is over the budget in {_years_text(over)}.")
    elif stats.avg_cost is None or stats.avg_cost > req.budget_usd:
        issues.append("Average farm cost is over the budget.")
    cap = req.water_available_af
    if cap is not None:
        over = [t.year for t in resp.farm_totals if t.water_applied_af > cap + 0.05]
        if over:
            issues.append(f"Water applied is over the limit in {_years_text(over)}.")
        if not any("never reached" in a for a in resp.assumptions):
            issues.append("The engine had to share out water under the limit, so the plan's "
                          "crops ran short.")
    if resp.land.over_capacity_months:
        issues.append("Land is over the available acres in "
                      f"{', '.join(resp.land.over_capacity_months)}.")
    for crop in {b.crop for b in blocks} | set(problem.locked):
        acres_c = sum(b.acres for b in blocks if b.crop == crop)
        if acres_c > req.max_share_per_crop * req.available_acres + 1e-6:
            issues.append(f"{_crop_label(crop)} is over the crop share limit.")
        if crop in problem.locked and abs(acres_c - problem.locked[crop]) > 1e-6:
            issues.append(f"{_crop_label(crop)} acres ({acres_c:g}) differ from the locked "
                          f"{problem.locked[crop]:g} acres.")
    return issues


# ---------------------------------------------------------------- explanations

def _years_text(years: list) -> str:
    years = sorted(years)
    if len(years) > 5:
        return f"{len(years)} of the years ({years[0]} to {years[-1]})"
    if len(years) == 1:
        return str(years[0])
    if len(years) == 2:
        return f"{years[0]} and {years[1]}"
    return ", ".join(map(str, years[:-1])) + f", and {years[-1]}"


def _months_text(months: set[int]) -> str:
    """Month runs, wrapping December: {5..9} -> "May to Sep", {11, 12, 1} -> "Nov to Jan"."""
    if len(months) == 12:
        return "all year"
    runs = []
    for m in range(1, 13):
        if m in months and (m - 2) % 12 + 1 not in months:  # m starts a run
            run, nxt = [m], m % 12 + 1
            while nxt in months:
                run.append(nxt)
                nxt = nxt % 12 + 1
            runs.append(run)
    parts = [MONTH_NAMES[r[0] - 1] if len(r) == 1
             else f"{MONTH_NAMES[r[0] - 1]} to {MONTH_NAMES[r[-1] - 1]}" for r in runs]
    return " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + f", and {parts[-1]}"


def binding_sentences(problem: Problem, sol: Solution) -> list[str]:
    """A limit binds when no block in the plan could grow by one 0.1 acre step without
    breaking it (acres move in steps, so a binding limit can keep a sliver of slack)."""
    req = problem.request
    used = sol.acres > 0
    hits: dict[str, list] = {}
    for r in sol.rows:
        if r.kind in ("cut", "keep") or not math.isfinite(r.ub):
            continue
        step = r.coeffs[used & (r.coeffs > 0)] * ACRE_STEP
        if step.size == 0:
            continue
        slack = r.ub - float(r.coeffs @ sol.acres)
        if slack < step.min() - BINDING_REL_TOL * max(1.0, abs(r.ub)):
            hits.setdefault(r.kind, []).append(r.label)
    out = []
    if "land" in hits:
        out.append(f"Land is fully used {_months_text(set(hits['land']))}.")
    if "budget" in hits:
        if req.budget_rule == "every_year":
            out.append(f"Budget is the limit in {_years_text(hits['budget'])}.")
        else:
            out.append("Budget is the limit on average.")
    if "water" in hits:
        out.append(f"Water limit is reached in {_years_text(hits['water'])}.")
    for crop in hits.get("share", []):
        out.append(f"{_crop_label(crop)} is at the {req.max_share_per_crop:.0%} crop share limit "
                   f"({req.max_share_per_crop * req.available_acres:,.1f} acres).")
    for crop in hits.get("locked", []):
        out.append(f"{_crop_label(crop)} acres are fixed at the current {problem.locked[crop]:g} "
                   "acres because new perennial plantings are off.")
    m_min = req.min_block_acres
    at_min = sum(1 for a in sol.acres if a > 0 and abs(a - m_min) < ACRE_STEP / 2)
    if m_min > 0 and at_min:
        out.append(f"{at_min} block{'s are' if at_min > 1 else ' is'} at the {m_min:g} acre minimum.")
    return out


def lock_reason(problem: Problem) -> str | None:
    """Plain English reason the locked perennial acres cannot fit, or None."""
    req = problem.request
    if problem.lock_errors:
        return " ".join(problem.lock_errors)
    if not problem.locked:
        return None
    names = " and ".join(_crop_noun(c) for c in problem.locked)
    total = sum(problem.locked.values())
    if total > req.available_acres + 1e-9:
        return (f"The locked {names} acres ({total:g}) are more than the "
                f"{req.available_acres:g} available acres.")
    for crop, acres in problem.locked.items():
        if 0 < acres < req.min_block_acres:
            return (f"The locked {_crop_noun(crop)} acres ({acres:g}) are less than the "
                    f"{req.min_block_acres:g} acre minimum block.")
        if acres > req.max_share_per_crop * req.available_acres + 1e-9:
            return (f"The locked {_crop_noun(crop)} acres ({acres:g}) are more than the "
                    f"{req.max_share_per_crop:.0%} crop share limit "
                    f"({req.max_share_per_crop * req.available_acres:g} acres).")
    # The cheapest and the least thirsty way to grow the locked acres, year by year.
    cheapest = sum(acres * np.min([o.cost for o in problem.options if o.crop == crop], axis=0)
                   for crop, acres in problem.locked.items())
    driest = sum(acres * np.min([o.water for o in problem.options if o.crop == crop], axis=0)
                 for crop, acres in problem.locked.items())
    if req.budget_rule == "every_year":
        over = [y for y, c in zip(problem.years, cheapest) if c > req.budget_usd]
        if over:
            return f"The locked {names} acres cost more than the budget in {_years_text(over)}."
    elif cheapest.mean() > req.budget_usd:
        return f"The locked {names} acres cost more than the budget on average."
    cap = req.water_available_af
    if cap is not None:
        over = [y for y, w in zip(problem.years, driest) if w > cap]
        if over:
            return f"The locked {names} acres need more water than the limit in {_years_text(over)}."
    return None


def _option_text(o: Option) -> str:
    k = o.key
    irr = k.irrigation.replace("_", " ")
    if k.crop in PERENNIALS:
        return f"{_crop_noun(k.crop)}, {irr}"
    return (f"{_crop_noun(k.crop)}, {irr}, {MONTH_NAMES[k.start_month - 1]} to "
            f"{MONTH_NAMES[k.end_month - 1]}")


def no_fit_reason(problem: Problem) -> str | None:
    """Why not even one minimum size block fits (when nothing is locked), or None."""
    req = problem.request
    if not problem.options:
        why = " ".join(problem.excluded) or "No crop and irrigation combination is allowed."
        return "No crop options are left to plan with. " + why
    size = max(req.min_block_acres, ACRE_STEP)
    room = min(req.available_acres, req.max_share_per_crop * req.available_acres)
    if size > room + 1e-9:
        return f"The {size:g} acre minimum block is larger than the {room:g} acres each crop can use."
    rule = "in its costliest year" if req.budget_rule == "every_year" else "on average"
    costs = [((o.cost.max() if req.budget_rule == "every_year" else o.cost.mean()) * size, o)
             for o in problem.options]
    cheapest, o = min(costs, key=lambda c: c[0])
    if cheapest > req.budget_usd:
        return (f"Even a {size:g} acre block of the cheapest option ({_option_text(o)}) costs "
                f"${cheapest:,.0f} {rule}, more than the ${req.budget_usd:,.0f} budget.")
    cap = req.water_available_af
    if cap is not None and all(o.water.max() * size > cap for o in problem.options):
        return (f"Even a {size:g} acre block of any option needs more water than the "
                f"{cap:g} acre-ft limit in at least one year.")
    return None


def optimizer_notes(problem: Problem) -> list[str]:
    req = problem.request
    notes = [
        f"The optimizer compared {len(problem.options)} options (crop, irrigation type, and "
        "planting month), each run for 1 acre through the same engine as /api/simulate. The "
        "plan's numbers come from running its blocks through that engine.",
        "Annual seasons last round(season_days / 30.44) whole months from the 1st of the "
        "planting month (5 months for each annual today). Planting months in crops.json are "
        "still marked to verify.",
        "Land is counted month by month, so a winter crop and a summer crop can share acres. "
        "Unplanted land has no cost and no income.",
        f"Acres are in steps of {ACRE_STEP:g} acre.",
        "Changing irrigation type does not include installation cost.",
        "Frost and cold damage are not modeled, so the earliest planting months can look "
        "better than they would be in the field.",
        PERENNIAL_LAG_NOTE,
    ]
    if req.budget_rule == "every_year":
        notes.append(f"Budget rule: farm cost is at or under ${req.budget_usd:,.0f} in every year.")
    else:
        notes.append(f"Budget rule: average farm cost is at or under ${req.budget_usd:,.0f}; "
                     "single years can go over.")
    if req.allow_new_perennials:
        notes.append("New perennial plantings are on and are counted as mature and fully "
                     "producing from the first year.")
    else:
        notes.append("New perennial plantings are off: each orchard or alfalfa crop keeps its "
                     "current acres, and its irrigation type can change. Perennials the "
                     "current farm does not grow are not planted.")
    if req.water_available_af is not None:
        notes.append(f"Water: full irrigation fits within the {req.water_available_af:,.1f} "
                     "acre-ft limit in every year, so no crop is planned into a shortage.")
    if req.objective == "production_value":
        notes.append("Production value is average yearly revenue at current prices, whatever "
                     "the price mode, so different crops are compared by value, not by tons.")
    return notes + list(problem.notes) + list(problem.excluded)


# ---------------------------------------------------------------- main entry point

def _diff(a: float | None, b: float | None, digits: int) -> float | None:
    return None if a is None or b is None else round(a - b, digits) + 0.0


def optimize(req: OptimizeRequest, wx=None, context: dict | None = None) -> OptimizeResponse:
    if wx is None:
        wx = engine.load_weather(req.location.lat, req.location.lon)
    if context is None:
        context = engine.get_location_context(req.location.lat, req.location.lon)
    ctx = LocationContext.model_validate(context).model_dump()
    wx = engine.prepare_weather(wx)

    current = None
    if req.current_farm is not None:
        resp = run_engine(req, req.current_farm.blocks, wx, ctx)
        current = OptimizeCurrentFarmOut(blocks=blocks_out(req.current_farm.blocks, resp),
                                         summary_stats=resp.summary_stats, budget=resp.budget)

    problem = build_problem(req, wx, ctx)

    def respond(status, **fields) -> OptimizeResponse:
        base = dict(objective=req.objective, plan=None, current_farm=current,
                    difference_vs_current=None, options_considered=len(problem.options),
                    assumptions=optimizer_notes(problem))
        return OptimizeResponse(status=status, **{**base, **fields})

    reason = lock_reason(problem) or (None if problem.locked else no_fit_reason(problem))
    if reason:
        return respond("infeasible", infeasible_reason=reason)

    sol = solve(problem, req.objective)
    if sol is None:
        return respond("infeasible", infeasible_reason=(
            "No plan meets the locked perennial acres and the land, budget, water, and crop "
            "share limits together."))
    blocks = plan_blocks(problem, sol.acres)
    if not blocks or (req.objective != "production_value" and sol.objective_value <= 0
                      and not problem.locked):
        noun = "makes money" if req.objective != "production_value" else "adds value"
        return respond("no_profitable_plan", infeasible_reason=(
            f"No allowed option {noun} on average over these years within the limits, so the "
            "highest scoring plan leaves the land unplanted."))

    resp = run_engine(req, blocks, wx, ctx)
    issues = verify(problem, sol.acres, blocks, resp)
    if issues:
        return respond("error", error_detail=" ".join(issues))

    plan = OptimizePlanOut(blocks=blocks_out(blocks, resp), summary_stats=resp.summary_stats,
                           budget=resp.budget, land=resp.land)
    diff = None
    if current is not None:
        p, c = plan.summary_stats, current.summary_stats
        diff = OptimizeDifferenceOut(
            avg_profit=_diff(p.avg_profit, c.avg_profit, 0),
            avg_yield_tons=_diff(p.avg_yield_tons, c.avg_yield_tons, 2),
            avg_water_applied_af=_diff(p.avg_water_applied_af, c.avg_water_applied_af, 1),
            avg_cost=_diff(p.avg_cost, c.avg_cost, 0))

    alternatives = build_alternatives(problem, sol, resp, wx, ctx)
    return respond(
        sol.status, plan=plan, difference_vs_current=diff, alternatives=alternatives,
        binding_constraints=binding_sentences(problem, sol),
        assumptions=list(dict.fromkeys(optimizer_notes(problem) + resp.assumptions)))


def build_alternatives(problem: Problem, best: Solution, best_resp: SimulateResponse, wx,
                       ctx: dict) -> list[OptimizeAlternativeOut]:
    """Re-solve with no-good cuts so each alternative uses a different set of options.

    A plan whose engine results are identical to one already shown (for example the
    same crop with another irrigation type when it applies no water) is cut but not
    listed, so every listed alternative is distinct in both options and results.
    """
    req = problem.request
    cuts = [no_good_cut(problem, {i for i, a in enumerate(best.acres) if a > 0})]
    seen = {best_resp.summary_stats.model_dump_json()}
    out: list[OptimizeAlternativeOut] = []
    for _ in range(MAX_ALTERNATIVE_SOLVES):
        if len(out) >= MAX_ALTERNATIVES:
            break
        sol = solve(problem, req.objective, cuts)
        if sol is None:
            break
        used = {i for i, a in enumerate(sol.acres) if a > 0}
        if not used:
            break
        cuts.append(no_good_cut(problem, used))
        blocks = plan_blocks(problem, sol.acres)
        resp = run_engine(req, blocks, wx, ctx)
        issues = verify(problem, sol.acres, blocks, resp)
        if issues:
            problem.notes["An alternative plan failed the engine check and was left out: "
                          + " ".join(issues)] = None
            continue
        stats = resp.summary_stats.model_dump_json()
        if stats in seen:
            continue
        seen.add(stats)
        out.append(OptimizeAlternativeOut(
            label=f"Alternative {len(out) + 1}", blocks=blocks_out(blocks, resp),
            summary_stats=resp.summary_stats, budget=resp.budget))
    return out
