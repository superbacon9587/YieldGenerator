"""Backtest engine: daily water balance, crop water use, and relative yield.

Main entry points:
    load_weather(lat, lon)        daily NASA POWER weather plus FAO-56 ET0 for a grid cell
    run_backtest(request, wx)     per block, per season results with daily detail kept
    simulate(request, wx=None)    the POST /api/simulate response (backend/schemas.py)

The engine only needs a weather DataFrame indexed by date with these columns:
    tmax_c, tmin_c, precip_mm_day, et0_mm_day
and df.attrs["lat"], df.attrs["lon"] for the grid cell. load_weather() builds that
from Marco's data layer (backend/power_client.py and backend/et0.py). Tests pass
synthetic weather in the same shape, so the engine never needs the network to test.

Method, per block and per season year:
 1. Season days. The block is in the field from the 1st of start_month to the last
    day of end_month. A season that wraps the new year (11 to 4) starts in the
    previous calendar year and is reported under the year it ends in.
 2. Crop coefficient. FAO-56 single Kc curve (Allen et al. 1998, ch. 6, Fig. 25):
    flat Kc ini, linear rise to Kc mid, flat Kc mid, linear fall to Kc end. Stage
    lengths come from crops.json and are stretched or shrunk to fit the season.
    A perennial planted year-round (1 to 12) keeps its own growing season from
    crops.json (season_start_month plus the stage days, not stretched); the rest
    of the year is dormant with Kc = Kc ini, which FAO-56 Table 12 treats as
    mostly soil evaporation under the trees.
 3. Crop water use ETc = Kc x ET0 (mm/day).
 4. Effective rain. Daily fixed-percentage method with a threshold (Dastane 1974,
    FAO Irrigation and Drainage Paper 25): rain below 5 mm/day is lost to
    interception and evaporation, and 80 percent of a larger rain enters the root
    zone. Rain that would push the root zone above field capacity drains away and
    is not counted as effective.
 5. Soil water balance. FAO-56 ch. 8 root zone depletion with a single Kc:
    TAW = available water capacity (soils.json) x root depth (ROOT_DEPTH_M),
    RAW = p x TAW with management allowed depletion p = 0.5. Water stress
    Ks = (TAW - Dr) / (TAW - RAW) once depletion passes RAW (FAO-56 eq. 84), and
    actual ET is ETa = Ks x ETc. The root zone starts each season at field
    capacity (winter rain or a pre-plant irrigation that is not counted).
 6. Irrigation. On active days (dormant perennials are not irrigated), when the
    depletion passes RAW the root zone is refilled to field capacity. Net need is
    that refill; water applied (gross) = net / irrigation efficiency
    (irrigation.json). Millimeters over the block's acres become acre-feet.
 7. Farm water cap. If optional.water_available_af is set and the farm's gross
    need in a year is larger, each block gets a share of the cap in proportion to
    its need. The block is then rerun with that budget: each irrigation refills
    only the budget fraction of the depletion, and stops when the budget runs out.
    The crop runs short and ETa falls below ETc.
 8. Relative yield. FAO-33 (Doorenbos and Kassam 1979):
    1 - Ya/Ym = Ky x (1 - ETa/ETc), summed over active days. Heat: a heat stress
    day is an active day with Tmax above the crop's heat_stress_c. Relative yield
    is "percent of a normal year" and normal yields already include normal heat,
    so only heat stress days above this block's normal count (the median over
    every season in the weather record). Each extra day cuts relative yield by
    HEAT_PENALTY_PER_DAY (0.25 percent), capped at HEAT_PENALTY_MAX (10 percent).
    That heat rule is a team assumption, not a published coefficient.
 9. Growing degree days. Simple average method, sum of max(0, (Tmax + Tmin)/2 -
    gdd_base_c) over active days, no upper cutoff.

Money, per block and season year (backend/economics.py helpers):
    revenue = (rounded relative_yield / median rounded relative_yield) x baseline_yield x acres x crop price
    cost    = cost_excl_water x acres + surface water cost + groundwater pumping cost
Baseline yields, production costs, and the surface water price come only from
get_location_context(lat, lon) (backend/regions.py, Marco's). Applied water is
split into surface water (optional.surface_water_share) priced at the context's
surface_water_price_per_af, and groundwater priced with the pumping cost
function (well lift and pump efficiency from defaults.json, electricity from
utilities.csv). A block with no baseline yield, crop price, or production cost
gets null revenue, cost, and profit, and a note in assumptions.

Waste flags are built in backend/waste.py. Harvest weight in tons (yield_weight) is built in
backend/yield_weight.py; summary_stats.avg_yield_tons is added by backend/summary.py.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import json
from dataclasses import dataclass, field
from functools import cache
from statistics import median

import numpy as np
import pandas as pd

from backend import economics, reference, waste, yield_weight
from backend.schemas import (
    PERENNIALS,
    BlockIn,
    BlockOut,
    BlockYearOut,
    FarmYearOut,
    LocationContext,
    LocationOut,
    SimulateRequest,
    SimulateResponse,
    SummaryOut,
)

# ---------------------------------------------------------------- location context

FALLBACK_NOTE = "Using Merced defaults until the California data layer is merged."


def _fallback_location_context(lat: float, lon: float) -> dict:
    """Merced-only stand-in for backend.regions.get_location_context, same shape.

    Used only when backend/regions.py is not importable. Baseline yields are the
    median of data/validation/merced_yields.csv, costs come from
    production_costs.csv (San Joaquin Valley North when present, else the latest
    study), and the water price from defaults.json.
    """
    data = reference.REFERENCE_DIR.parent
    yields: dict[str, list[tuple[float, str]]] = {}
    with (data / "validation" / "merced_yields.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            if r["yield"]:
                yields.setdefault(r["crop"], []).append((float(r["yield"]), r["unit"]))
    baseline = {
        crop: {"value": median(v for v, _ in rows), "unit": rows[0][1], "basis": "county",
               "source": f"NASS Merced County median, {len(rows)} years"}
        for crop, rows in yields.items()
    }
    costs: dict[str, dict] = {}
    with (economics.PRICES_DIR / "production_costs.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            if not r["cost_excl_water"] or "organic" in r["region"].lower():
                continue
            prev = costs.get(r["crop"])
            sjv = r["region"] == "San Joaquin Valley North"
            if prev is None or (sjv and prev["region"] != r["region"]) or (
                    prev["region"] != "San Joaquin Valley North"
                    and int(r["study_year"]) > int(prev["_year"])):
                costs[r["crop"]] = {"cost_excl_water": float(r["cost_excl_water"]),
                                    "unit": "$ / ACRE", "region": r["region"],
                                    "source": f"UC Davis cost study {r['source']}",
                                    "_year": r["study_year"]}
    for c in costs.values():
        c.pop("_year")
    water = json.loads((economics.PRICES_DIR / "defaults.json").read_text())
    return {
        "state": "CA", "county": "Merced", "in_california": True,
        "cost_region": "San Joaquin Valley North",
        "baseline_yields": baseline,
        "production_costs": costs,
        "surface_water_price_per_af": water["surface_water_price_per_af"]["value"],
        "data_quality": [FALLBACK_NOTE],
    }


try:
    from backend.regions import get_location_context
except ImportError:  # Marco's module not merged yet
    get_location_context = _fallback_location_context

# ---------------------------------------------------------------- constants

MM_PER_IN = 25.4
MM_PER_FT = 304.8

# Management allowed depletion (fraction of TAW) before irrigating.
MAD_P = 0.5

# Effective rain: threshold and fraction (Dastane 1974, FAO I&D Paper 25).
RAIN_THRESHOLD_MM = 5.0
RAIN_EFFECTIVE_FRACTION = 0.8

# Heat stress yield cut, a team assumption (see module docstring).
HEAT_PENALTY_PER_DAY = 0.0025
HEAT_PENALTY_MAX = 0.10

# Effective root depth in m: midpoints of the FAO-56 Table 22 ranges (max
# effective rooting depth Zr). Held constant through the season.
ROOT_DEPTH_M = {
    "almonds": 1.5,               # Table 22, almonds 1.0 to 2.0
    "walnuts": 2.0,               # Table 22, walnut orchard 1.7 to 2.4
    "processing_tomatoes": 1.1,   # Table 22, tomato 0.7 to 1.5
    "corn": 1.35,                 # Table 22, maize (grain) 1.0 to 1.7
    "oats": 1.25,                 # Table 22, oats 1.0 to 1.5
    "alfalfa_hay": 1.5,           # Table 22, alfalfa for hay 1.0 to 2.0
}

DROUGHT_YEARS = (2014, 2015, 2021, 2022)

# Contract irrigation ids -> irrigation.json keys.
IRRIGATION_KEYS = {"micro_sprinkler": "micro-sprinkler"}

WEATHER_COLUMNS = ["tmax_c", "tmin_c", "precip_mm_day", "et0_mm_day"]

ASSUMPTIONS = [
    "Mature, full-producing orchards.",
    "Weather is regional (NASA POWER grid cell about 50 km wide).",
    "Yield losses from weather and water only. Nutrients, pests, and disease are assumed well managed.",
    "Reference ET0 is FAO-56 Penman-Monteith from NASA POWER daily weather.",
    "Crop water use is ETc = Kc x ET0 with the FAO-56 single crop coefficient curve.",
    "Effective rain: rain under 5 mm in a day is lost, and 80 percent of larger rains "
    "reach the root zone (Dastane 1974, FAO Irrigation and Drainage Paper 25).",
    "Irrigation refills the root zone when half of the available water is used "
    "(FAO-56 soil water balance). The root zone starts each season full.",
    "Relative yield uses FAO-33: 1 - Ya/Ym = Ky x (1 - ETa/ETc). Each heat stress day above "
    "this location's normal count takes another 0.25 percent off, up to 10 percent.",
    "Seasons that cross the new year are counted in the year they end.",
    "Dormant orchards and alfalfa are not irrigated outside their growing season.",
]


class WeatherUnavailableError(ValueError):
    """The requested seasons need days that the weather record does not cover."""


# ---------------------------------------------------------------- weather

def load_weather(lat: float, lon: float) -> pd.DataFrame:
    """Daily weather for the POWER grid cell containing (lat, lon), with ET0."""
    from backend import power_client
    from backend.et0 import et0_fao56

    df = power_client.get_daily(lat, lon)
    out = pd.DataFrame({
        "tmax_c": df["tmax_c"],
        "tmin_c": df["tmin_c"],
        "precip_mm_day": df["precip_mm_day"],
        "et0_mm_day": et0_fao56(df),
    })
    out.attrs = {"lat": df.attrs["lat"], "lon": df.attrs["lon"],
                 "elevation_m": df.attrs.get("elevation_m")}
    return out


def prepare_weather(wx: pd.DataFrame) -> pd.DataFrame:
    """Check columns and fill short gaps so the daily loop never sees NaN."""
    missing = [c for c in WEATHER_COLUMNS if c not in wx.columns]
    if missing:
        raise ValueError(f"Weather is missing columns: {missing}")
    out = wx[WEATHER_COLUMNS].copy()
    out.index = pd.DatetimeIndex(out.index).normalize()
    for col in ("tmax_c", "tmin_c", "et0_mm_day"):
        out[col] = out[col].interpolate(limit_direction="both")
    out["precip_mm_day"] = out["precip_mm_day"].fillna(0.0)
    out["et0_mm_day"] = out["et0_mm_day"].clip(lower=0.0)
    out.attrs = dict(wx.attrs)
    return out


# ---------------------------------------------------------------- season and Kc

def season_dates(block: BlockIn, year: int) -> tuple[dt.date, dt.date]:
    """First and last day in the field for the season reported under `year`."""
    start_year = year - 1 if block.wraps_year else year
    start = dt.date(start_year, block.start_month, 1)
    end = dt.date(year, block.end_month, calendar.monthrange(year, block.end_month)[1])
    return start, end


def scale_stages(stage_days: dict, n_days: int) -> list[int]:
    """Stretch or shrink [ini, dev, mid, late] to sum to n_days, keeping proportions."""
    lengths = [stage_days[k] for k in ("ini", "dev", "mid", "late")]
    total = sum(lengths)
    scaled = [round(n * n_days / total) for n in lengths]
    scaled[2] += n_days - sum(scaled)  # rounding remainder goes to mid season
    return scaled


def kc_curve(kc: dict, stage_lengths: list[int]) -> np.ndarray:
    """Daily FAO-56 Kc: flat ini, linear dev, flat mid, linear late."""
    ini, dev, mid, late = stage_lengths
    k_ini, k_mid, k_end = kc["ini"], kc["mid"], kc["end"]
    parts = [
        np.full(ini, k_ini),
        k_ini + (k_mid - k_ini) * (np.arange(1, dev + 1) / dev) if dev else np.empty(0),
        np.full(mid, k_mid),
        k_mid + (k_end - k_mid) * (np.arange(1, late + 1) / late) if late else np.empty(0),
    ]
    return np.concatenate(parts)


def season_kc(params: dict, crop: str, block: BlockIn, start: dt.date,
              n_days: int) -> tuple[np.ndarray, np.ndarray]:
    """Kc for each season day and a mask of active (growing) days."""
    year_round = len(block.months) == 12
    if crop in PERENNIALS and year_round:
        # Own growing season inside the calendar year, dormant the rest.
        kc = np.full(n_days, params["kc"]["ini"])
        active = np.zeros(n_days, dtype=bool)
        lengths = [params["stage_days"][k] for k in ("ini", "dev", "mid", "late")]
        offset = (dt.date(start.year, params["season_start_month"], 1) - start).days
        curve = kc_curve(params["kc"], lengths)[: max(n_days - offset, 0)]
        kc[offset: offset + len(curve)] = curve
        active[offset: offset + len(curve)] = True
        return kc, active
    return kc_curve(params["kc"], scale_stages(params["stage_days"], n_days)), np.ones(n_days, bool)


def effective_rain_mm(precip_mm: np.ndarray) -> np.ndarray:
    """Rain that reaches the root zone, before the field capacity limit."""
    p = np.asarray(precip_mm, dtype=float)
    return np.where(p >= RAIN_THRESHOLD_MM, RAIN_EFFECTIVE_FRACTION * p, 0.0)


def mm_to_af(mm: float, acres: float) -> float:
    return mm / MM_PER_FT * acres


def af_to_mm(af: float, acres: float) -> float:
    return af * MM_PER_FT / acres if acres else 0.0


# ---------------------------------------------------------------- water balance

@dataclass
class WaterBalance:
    """Daily arrays for one season, all in mm except ks."""
    etc: np.ndarray
    eta: np.ndarray
    rain_in: np.ndarray         # effective rain reaching the soil, before the capacity limit
    rain_eff: np.ndarray        # effective rain actually stored in the root zone
    irrigation_net: np.ndarray
    depletion: np.ndarray       # end of day root zone depletion
    ks: np.ndarray


def water_balance(et0: np.ndarray, precip: np.ndarray, kc: np.ndarray, active: np.ndarray,
                  taw: float, raw: float, budget_mm: float | None = None,
                  ration: float = 1.0) -> WaterBalance:
    """FAO-56 root zone depletion, one step per day.

    budget_mm caps total net irrigation for the season. ration (0 to 1) is the
    fraction of the depletion each irrigation refills when water is short.
    """
    n = len(et0)
    etc = kc * et0
    pe_in = effective_rain_mm(precip)
    eta = np.zeros(n)
    rain_eff = np.zeros(n)
    irr = np.zeros(n)
    dep = np.zeros(n)
    ks_out = np.ones(n)
    remaining = float("inf") if budget_mm is None else budget_mm

    dr = 0.0
    for i in range(n):
        # FAO-56 eq. 85: Dr,i = Dr,i-1 - P - I + ETa. Rain beyond field capacity drains.
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / (taw - raw))
        a = ks * etc[i]
        dr = dr - pe_in[i] + a
        drained = max(-dr, 0.0)
        dr = min(max(dr, 0.0), taw)
        stored = pe_in[i] - drained
        if active[i] and dr > raw and remaining > 0:
            amount = min(dr * ration, remaining)
            dr -= amount
            remaining -= amount
            irr[i] = amount
        eta[i], rain_eff[i], dep[i], ks_out[i] = a, stored, dr, ks
    return WaterBalance(etc, eta, pe_in, rain_eff, irr, dep, ks_out)


# ---------------------------------------------------------------- one block, one season

@dataclass
class BlockSeason:
    block_id: str
    crop: str
    acres: float
    irrigation: str
    efficiency: float
    year: int
    start: dt.date
    end: dt.date
    dates: pd.DatetimeIndex
    active: np.ndarray
    balance: WaterBalance
    need_net_mm: float           # net irrigation need with unlimited water
    applied_net_mm: float        # net irrigation actually applied (lower if capped)
    relative_yield: float
    heat_stress_days: int
    gdd: float
    capped: bool = False
    revenue: float | None = None
    cost: float | None = None

    @property
    def profit(self) -> float | None:
        if self.revenue is None or self.cost is None:
            return None
        return self.revenue - self.cost

    @property
    def irrigation_need_af(self) -> float:
        return mm_to_af(self.need_net_mm, self.acres)

    @property
    def gross_need_af(self) -> float:
        return self.irrigation_need_af / self.efficiency

    @property
    def water_applied_af(self) -> float:
        return mm_to_af(self.applied_net_mm, self.acres) / self.efficiency

    @property
    def crop_water_use_in(self) -> float:
        return float(self.balance.etc.sum()) / MM_PER_IN

    @property
    def effective_rain_in(self) -> float:
        return float(self.balance.rain_eff.sum()) / MM_PER_IN


def relative_yield(ky: float, eta_sum: float, etc_sum: float, extra_heat_days: float) -> float:
    """FAO-33 Ky response plus the heat stress cut, clipped to [0, 1].

    extra_heat_days is heat stress days above the location's normal count.
    """
    water = 1.0 - ky * (1.0 - eta_sum / etc_sum) if etc_sum > 0 else 1.0
    heat = min(max(extra_heat_days, 0) * HEAT_PENALTY_PER_DAY, HEAT_PENALTY_MAX)
    return float(min(max(water - heat, 0.0), 1.0))


def irrigation_efficiency(system: str) -> float:
    return reference.irrigation_efficiency(IRRIGATION_KEYS.get(system, system))


def _season_days(block: BlockIn, year: int, wx: pd.DataFrame):
    """Weather rows for the season, or None if the record does not cover it."""
    start, end = season_dates(block, year)
    days = wx.loc[pd.Timestamp(start): pd.Timestamp(end)]
    return (start, end, days) if len(days) == (end - start).days + 1 else None


def count_heat_days(params: dict, block: BlockIn, start: dt.date, tmax: np.ndarray) -> int:
    _, active = season_kc(params, block.crop, block, start, len(tmax))
    return int(np.sum(active & (tmax > params["heat_stress_c"])))


def normal_heat_days(block: BlockIn, wx: pd.DataFrame) -> float:
    """Median heat stress days for this block over every season the record covers."""
    params = reference.crop_params(block.crop)
    counts = []
    for year in range(wx.index.min().year, wx.index.max().year + 1):
        found = _season_days(block, year, wx)
        if found:
            start, _, days = found
            counts.append(count_heat_days(params, block, start, days["tmax_c"].to_numpy()))
    return float(np.median(counts)) if counts else 0.0


def simulate_block_season(block: BlockIn, year: int, wx: pd.DataFrame, soil: str,
                          budget_net_mm: float | None = None,
                          normal_heat: float = 0.0) -> BlockSeason:
    params = reference.crop_params(block.crop)
    found = _season_days(block, year, wx)
    if found is None:
        start, end = season_dates(block, year)
        first, last = wx.index.min().date(), wx.index.max().date()
        raise WeatherUnavailableError(
            f"Block {block.id} season {year} needs weather from {start} to {end}; "
            f"available {first} to {last}.")
    start, end, days = found
    n = len(days)

    kc, active = season_kc(params, block.crop, block, start, n)
    taw = reference.soil_awc_mm_per_m(soil) * ROOT_DEPTH_M[block.crop]
    raw = MAD_P * taw
    et0 = days["et0_mm_day"].to_numpy()
    precip = days["precip_mm_day"].to_numpy()

    full = water_balance(et0, precip, kc, active, taw, raw)
    need = float(full.irrigation_net.sum())
    bal, applied, capped = full, need, False
    if budget_net_mm is not None and budget_net_mm < need - 1e-9:
        ration = budget_net_mm / need if need else 0.0
        bal = water_balance(et0, precip, kc, active, taw, raw,
                            budget_mm=budget_net_mm, ration=ration)
        applied, capped = float(bal.irrigation_net.sum()), True

    tmax = days["tmax_c"].to_numpy()
    tmin = days["tmin_c"].to_numpy()
    heat_days = int(np.sum(active & (tmax > params["heat_stress_c"])))
    gdd = float(np.sum(np.where(active, np.maximum((tmax + tmin) / 2 - params["gdd_base_c"], 0), 0)))
    ry = relative_yield(params["ky"], float(bal.eta[active].sum()),
                        float(bal.etc[active].sum()), heat_days - normal_heat)

    return BlockSeason(
        block_id=block.id, crop=block.crop, acres=block.acres, irrigation=block.irrigation,
        efficiency=irrigation_efficiency(block.irrigation), year=year, start=start, end=end,
        dates=days.index, active=active, balance=bal, need_net_mm=need, applied_net_mm=applied,
        relative_yield=ry, heat_stress_days=heat_days, gdd=gdd, capped=capped)


# ---------------------------------------------------------------- whole farm

@dataclass
class Backtest:
    request: SimulateRequest
    years: list[int]
    grid_cell: tuple[float, float]
    seasons: dict[str, dict[int, BlockSeason]]       # block id -> year -> season
    assumptions: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)      # get_location_context output
    water_cost_per_af: dict[int, float | None] = field(default_factory=dict)
    money_notes: list[str] = field(default_factory=list)


def run_backtest(request: SimulateRequest, wx: pd.DataFrame) -> Backtest:
    """Water and yield for every block and season year, with the farm water cap."""
    wx = prepare_weather(wx)
    soil = request.optional.soil
    cap = request.optional.water_available_af
    years = list(range(request.years[0], request.years[1] + 1))
    seasons: dict[str, dict[int, BlockSeason]] = {b.id: {} for b in request.blocks}
    any_capped = False
    normals = {b.id: normal_heat_days(b, wx) for b in request.blocks}

    for year in years:
        free = {b.id: simulate_block_season(b, year, wx, soil, normal_heat=normals[b.id])
                for b in request.blocks}
        total_gross = sum(s.gross_need_af for s in free.values())
        if cap is not None and total_gross > cap:
            for b in request.blocks:
                share_gross_af = cap * free[b.id].gross_need_af / total_gross
                budget_net_mm = af_to_mm(share_gross_af * free[b.id].efficiency, b.acres)
                seasons[b.id][year] = simulate_block_season(
                    b, year, wx, soil, budget_net_mm, normal_heat=normals[b.id])
            any_capped = True
        else:
            for b in request.blocks:
                seasons[b.id][year] = free[b.id]

    assumptions = list(ASSUMPTIONS)
    if cap is not None:
        assumptions.append(
            f"Farm water is capped at {cap:,.1f} acre-ft per year, split across blocks in "
            "proportion to need." + ("" if any_capped else " The cap was never reached."))
    unverified = sorted({b.crop for b in request.blocks if reference.unverified_fields(b.crop)})
    if unverified:
        assumptions.append(
            "Some crop parameters are placeholders still being checked against FAO sources: "
            + ", ".join(unverified) + ".")
    grid = (float(wx.attrs.get("lat", request.location.lat)),
            float(wx.attrs.get("lon", request.location.lon)))
    return Backtest(request, years, grid, seasons, assumptions)


# ---------------------------------------------------------------- money

ELECTRICITY_SERIES = "electricity_commercial"


@cache
def _price_tables():
    return (economics.load_crop_prices(), economics.load_utility_prices(),
            economics.load_defaults())


def _lookup_price(table: economics.PriceTable, key: str, year: int, mode: str,
                  notes: dict, label: str) -> economics.Price | None:
    """Price for the year. In historical mode a missing year uses the nearest year."""
    try:
        return table.get(key, year, mode)
    except economics.PriceNotFoundError:
        if mode != "historical":
            return None
    for gap in range(1, 60):
        for y in (year - gap, year + gap):
            try:
                price = table.get(key, y, "historical")
            except economics.PriceNotFoundError:
                continue
            notes[f"Some years have no {label} price, so the nearest year's price is used."] = None
            return price
    return None


def apply_money(bt: Backtest, ctx: dict) -> None:
    """Fill revenue and cost on every season, and water cost per acre-ft per year."""
    req = bt.request
    crop_prices, utilities, defaults = _price_tables()
    mode = req.price_mode
    share = req.optional.surface_water_share
    sw_price = ctx.get("surface_water_price_per_af")
    lift, pump_eff = defaults["well_lift_ft"], defaults["pump_efficiency"]
    notes: dict[str, None] = {}  # ordered set

    pump_cost: dict[int, float | None] = {}
    for y in bt.years:
        elec = _lookup_price(utilities, ELECTRICITY_SERIES, y, mode, notes, "electricity")
        pump_cost[y] = (economics.pumping_cost_per_af(lift, pump_eff, elec.value, elec.unit)
                        if elec else None)
        sw_part = share * sw_price if sw_price is not None else (0.0 if share == 0 else None)
        gw_part = (1 - share) * pump_cost[y] if pump_cost[y] is not None else (
            0.0 if share == 1 else None)
        bt.water_cost_per_af[y] = (sw_part + gw_part
                                   if sw_part is not None and gw_part is not None else None)

    for b in req.blocks:
        label = b.crop.replace("_", " ")
        base = ctx["baseline_yields"].get(b.crop)
        prod = ctx["production_costs"].get(b.crop)
        relative = [round(bt.seasons[b.id][y].relative_yield, 3) for y in bt.years]
        typical = median(relative)
        missing: dict[str, None] = {}
        if not typical:
            missing["nonzero median modeled yield"] = None
        if base is None:
            missing["baseline yield"] = None
        if prod is None:
            missing["production cost"] = None
        for y, s in bt.seasons[b.id].items():
            price = _lookup_price(crop_prices, b.crop, y, mode, notes, label)
            if price is None:
                missing["crop price"] = None
            if bt.water_cost_per_af[y] is None:
                missing["water price"] = None
            if price is None or base is None or prod is None or bt.water_cost_per_af[y] is None or not typical:
                s.revenue = s.cost = None
                continue
            per_acre = economics.convert_quantity(base["value"], base["unit"], price.unit, b.crop)
            s.revenue = round(s.relative_yield, 3) / typical * per_acre * b.acres * price.value
            s.cost = (prod["cost_excl_water"] * b.acres
                      + s.water_applied_af * bt.water_cost_per_af[y])
        if missing:
            notes[f"Block {b.id} ({label}) has no {' or '.join(missing)}, so its revenue, "
                  "cost, and profit are shown as no data."] = None

    notes["Revenue uses the same median-normalized harvest quantity as the harvest-weight display."] = None
    if mode == "current":
        notes["Prices: the latest USDA NASS price for each crop is used for every year."] = None
    else:
        notes["Prices: each year uses that year's USDA NASS price."] = None
    last = bt.years[-1]
    if sw_price is not None and pump_cost.get(last) is not None:
        notes[f"Applied water is {share:.0%} surface water at ${sw_price:,.0f} per acre-ft and "
              f"{1 - share:.0%} groundwater pumped from {lift:g} ft (about "
              f"${pump_cost[last]:,.0f} per acre-ft in {last})."] = None
    bt.money_notes = list(notes)


# ---------------------------------------------------------------- response

def _money(x: float | None) -> float | None:
    return None if x is None else round(x)


def _block_year_out(s: BlockSeason) -> BlockYearOut:
    return BlockYearOut(
        year=s.year,
        crop_water_use_in=round(s.crop_water_use_in, 1),
        effective_rain_in=round(s.effective_rain_in, 1),
        irrigation_need_af=round(s.irrigation_need_af, 1),
        water_applied_af=round(s.water_applied_af, 1),
        relative_yield=round(s.relative_yield, 3),
        heat_stress_days=s.heat_stress_days,
        gdd=round(s.gdd),
        revenue=_money(s.revenue), cost=_money(s.cost), profit=_money(s.profit),
    )


def summarize(years: list[int], farm: list[FarmYearOut]) -> tuple[SummaryOut, str]:
    """Best, worst, and typical year. Ranked by profit when every year has one,
    otherwise by relative yield. Returns the summary and the metric name."""
    if all(f.profit is not None for f in farm):
        key, metric = (lambda f: f.profit), "farm profit"
    else:
        key, metric = (lambda f: f.relative_yield), "farm relative yield"
    ranked = sorted(farm, key=key)
    return SummaryOut(
        best_year=ranked[-1].year,
        worst_year=ranked[0].year,
        typical_year=ranked[(len(ranked) - 1) // 2].year,
        drought_years=[y for y in DROUGHT_YEARS if years[0] <= y <= years[-1]],
    ), metric


def _sum_or_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present)) if present else None


def build_response(bt: Backtest) -> SimulateResponse:
    req, ctx = bt.request, bt.context
    blocks = [
        BlockOut(id=b.id, crop=b.crop, acres=b.acres, irrigation=b.irrigation,
                 yearly=[_block_year_out(bt.seasons[b.id][y]) for y in bt.years])
        for b in req.blocks
    ]
    total_acres = sum(b.acres for b in req.blocks)
    farm = []
    left_out: dict[str, None] = {}
    for y in bt.years:
        ss = [bt.seasons[b.id][y] for b in req.blocks]
        with_money = [s for s in ss if s.profit is not None]
        if with_money:
            for s in ss:
                if s.profit is None:
                    left_out[f"{s.block_id} ({s.crop.replace('_', ' ')})"] = None
        farm.append(FarmYearOut(
            year=y,
            water_applied_af=round(sum(s.water_applied_af for s in ss), 1),
            relative_yield=round(sum(s.relative_yield * s.acres for s in ss) / total_acres, 3),
            revenue=_sum_or_none([s.revenue for s in with_money]),
            cost=_sum_or_none([s.cost for s in with_money]),
            profit=_sum_or_none([s.profit for s in with_money]),
        ))
    summary, metric = summarize(bt.years, farm)

    assumptions = list(bt.assumptions) + list(ctx.get("data_quality", [])) + bt.money_notes
    if left_out:
        assumptions.append("Farm dollar totals only add up blocks with price data (left out: "
                           + ", ".join(left_out) + ").")
    assumptions.append(f"The summary's high, low, and typical years are ranked by {metric}.")

    # Harvest weight in tons (backend/yield_weight.py).
    weight_notes: dict[str, None] = {}
    weights = yield_weight.build_yield_weight(blocks, ctx, weight_notes)
    assumptions.extend(yield_weight.assumptions(weights, weight_notes))

    return SimulateResponse(
        location=LocationOut(label=req.location.label, grid_cell=bt.grid_cell,
                             county=ctx.get("county"), cost_region=ctx.get("cost_region")),
        years=bt.years,
        blocks=blocks,
        farm_totals=farm,
        summary=summary,
        waste_flags=waste.build_flags(bt),
        assumptions=assumptions,
        yield_weight=weights,
    )


def simulate(request: SimulateRequest, wx: pd.DataFrame | None = None,
             context: dict | None = None, *,
             include_comparisons: bool = True) -> SimulateResponse:
    """Run the backtest for a request.

    Weather is loaded from NASA POWER and the location context from
    get_location_context when they are not passed in.
    """
    if wx is None:
        wx = load_weather(request.location.lat, request.location.lon)
    if context is None:
        context = get_location_context(request.location.lat, request.location.lon)
    ctx = LocationContext.model_validate(context).model_dump()
    bt = run_backtest(request, wx)
    bt.context = ctx
    apply_money(bt, ctx)
    response = build_response(bt)
    # Frost within 45 days of planting for annual blocks (backend/frost.py), as neutral facts.
    from backend import frost
    response.assumptions.extend(frost.block_notes(request.blocks, prepare_weather(wx), bt.years))
    if include_comparisons:
        from backend.comparisons import build_comparisons
        response.comparisons = build_comparisons(request, response, wx=wx, context=ctx)
    from backend import summary
    response = summary.add_to_response(response, request, ctx)
    if include_comparisons:
        from backend import calculations
        response.calculation_details = calculations.build(bt, response, wx)
    return response
