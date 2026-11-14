"""Waste flags: places where a farm likely uses more water than it needs.

build_flags(backtest) returns WasteFlagOut items, largest estimated savings
first. Every estimate is an average per year over the backtest years. Dollar
estimates use the farm's blended water cost per acre-ft (surface water share at
the surface water price, the rest at the groundwater pumping cost), averaged
over the same years; they are None when no water price is known.

Flag types:
  irrigation_method  Water lost because the block's irrigation method is less
                     efficient than drip: gross applied minus net need / drip
                     efficiency (efficiencies from irrigation.json).
  over_applied       optional.water_applied_af is above the modeled gross need
                     for the whole farm. This flag is farm wide, so its
                     block_id is "farm".
  rain_covered       Irrigation in weeks (7 day steps from the season start)
                     where effective rain already met or beat the crop's water
                     use, so the irrigation mostly drained past the roots.
                     Estimate is the gross water applied in those weeks.
  low_holding_soil   A high water use crop (season ETc of HIGH_WATER_IN inches
                     or more) on sand. Sand holds little water, so more drains
                     past the roots. Estimate is SAND_EXTRA_LOSS (10 percent) of
                     water applied, a rough team rule of thumb, not a measured
                     value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from backend import reference
from backend.schemas import WasteFlagOut

if TYPE_CHECKING:
    from backend.simulate import Backtest, BlockSeason

MIN_AF_PER_YEAR = 0.5           # ignore savings smaller than this
OVER_APPLIED_TOLERANCE = 0.05   # reported water within 5 percent of need is fine
WEEK_DAYS = 7
HIGH_WATER_IN = 30.0
SAND_EXTRA_LOSS = 0.10
MM_PER_FT = 304.8

METHOD_LABELS = {"flood": "Flood", "sprinkler": "Sprinkler", "micro_sprinkler": "Micro-sprinkler"}


def _crop(crop: str) -> str:
    return crop.replace("_", " ")


def _af(x: float) -> str:
    return f"{x:,.1f}" if x < 10 else f"{x:,.0f}"


def _flag(bt: Backtest, block_id: str, kind: str, message: str, af: float) -> WasteFlagOut:
    costs = [c for c in bt.water_cost_per_af.values() if c is not None]
    per_af = float(np.mean(costs)) if costs else None
    return WasteFlagOut(
        block_id=block_id, type=kind, message=message,
        estimated_af_per_year=round(af, 1),
        estimated_cost_per_year=None if per_af is None else round(af * per_af),
    )


def _seasons(bt: Backtest, block_id: str) -> list[BlockSeason]:
    return [bt.seasons[block_id][y] for y in bt.years]


def irrigation_method_flags(bt: Backtest) -> list[WasteFlagOut]:
    drip = reference.irrigation_efficiency("drip")
    flags = []
    for b in bt.request.blocks:
        if b.irrigation == "drip":
            continue
        ss = _seasons(bt, b.id)
        loss = float(np.mean([s.water_applied_af - s.water_applied_af * s.efficiency / drip
                              for s in ss]))
        if loss >= MIN_AF_PER_YEAR:
            flags.append(_flag(
                bt, b.id, "irrigation_method",
                f"{METHOD_LABELS.get(b.irrigation, b.irrigation)} irrigation on {_crop(b.crop)} "
                f"loses about {_af(loss)} acre-ft per year compared with drip.", loss))
    return flags


def over_applied_flags(bt: Backtest) -> list[WasteFlagOut]:
    reported = bt.request.optional.water_applied_af
    if reported is None:
        return []
    need = float(np.mean([sum(bt.seasons[b.id][y].gross_need_af for b in bt.request.blocks)
                          for y in bt.years]))
    excess = reported - need
    if excess < max(MIN_AF_PER_YEAR, OVER_APPLIED_TOLERANCE * need):
        return []
    return [_flag(
        bt, "farm", "over_applied",
        f"You apply about {_af(reported)} acre-ft per year, but your crops need about "
        f"{_af(need)} acre-ft with your irrigation systems. That is about {_af(excess)} "
        "acre-ft more than needed.", excess)]


def rain_covered_flags(bt: Backtest) -> list[WasteFlagOut]:
    flags = []
    for b in bt.request.blocks:
        wasted, weeks = [], []
        for s in _seasons(bt, b.id):
            bal = s.balance
            af, n = 0.0, 0
            for i in range(0, len(bal.etc), WEEK_DAYS):
                w = slice(i, i + WEEK_DAYS)
                irr = bal.irrigation_net[w].sum()
                if irr > 0 and bal.rain_in[w].sum() >= bal.etc[w].sum():
                    af += irr / MM_PER_FT * s.acres / s.efficiency
                    n += 1
            wasted.append(af)
            weeks.append(n)
        avg = float(np.mean(wasted))
        if avg >= MIN_AF_PER_YEAR:
            w = float(np.mean(weeks))
            when = f"about {w:.0f} weeks a year" if w >= 1.5 else "some weeks"
            flags.append(_flag(
                bt, b.id, "rain_covered",
                f"Block {b.id} ({_crop(b.crop)}) was watered in {when} when rain already "
                "covered the crop's needs. Checking the forecast before irrigating could save "
                f"about {_af(avg)} acre-ft per year.", avg))
    return flags


def low_holding_soil_flags(bt: Backtest) -> list[WasteFlagOut]:
    if bt.request.optional.soil != "sand":
        return []
    flags = []
    for b in bt.request.blocks:
        ss = _seasons(bt, b.id)
        if np.mean([s.crop_water_use_in for s in ss]) < HIGH_WATER_IN:
            continue
        loss = SAND_EXTRA_LOSS * float(np.mean([s.water_applied_af for s in ss]))
        if loss >= MIN_AF_PER_YEAR:
            flags.append(_flag(
                bt, b.id, "low_holding_soil",
                f"Block {b.id} ({_crop(b.crop)}) needs a lot of water, and sandy soil holds "
                "little, so more drains past the roots. Shorter, more frequent irrigations could save "
                f"roughly {_af(loss)} acre-ft per year.", loss))
    return flags


def build_flags(bt: Backtest) -> list[WasteFlagOut]:
    flags = (irrigation_method_flags(bt) + over_applied_flags(bt)
             + rain_covered_flags(bt) + low_holding_soil_flags(bt))
    return sorted(flags, key=lambda f: f.estimated_af_per_year, reverse=True)
