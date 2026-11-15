"""Frost check for annual planting windows, from NASA POWER daily minimum temperature.

Main entry points:
    frost_risk(wx, start_month, end_month, years)  -> FrostRisk
    block_notes(blocks, wx, years)                  -> plain sentences for assumptions

A planting window has frost in a season when the daily minimum temperature
(tmin_c, NASA POWER T2M_MIN) is at or below 0 C on any of the first 45 days
after planting, counting the planting day (the 1st of start_month) as day 1.
Season years follow simulate.season_dates: a season that wraps the new year
(start_month > end_month) is reported under the year it ends in, so its
planting date is in the year before. frost_risk_share is the fraction of the
backtest years with frost; years whose 45 days are not all in the weather
record are not counted.

Perennials are year-round and are not checked. The optimizer leaves out
options for crops that are not frost tolerant (crops.json frost_tolerant)
when frost_risk_share is above FROST_SHARE_LIMIT.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.schemas import PERENNIALS

FROST_C = 0.0
FROST_WINDOW_DAYS = 45
FROST_SHARE_LIMIT = 0.2
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class FrostRisk:
    frost_years: int     # backtest years with frost in the first 45 days after planting
    years: int           # backtest years checked

    @property
    def share(self) -> float | None:
        """frost_risk_share, 0 to 1. None when no year could be checked."""
        return self.frost_years / self.years if self.years else None

    @property
    def above_limit(self) -> bool:
        return self.share is not None and self.share > FROST_SHARE_LIMIT


def planting_date(start_month: int, end_month: int, year: int) -> pd.Timestamp:
    """Planting day for the season reported under `year` (wrapping seasons start a year earlier)."""
    start_year = year - 1 if start_month > end_month else year
    return pd.Timestamp(start_year, start_month, 1)


def frost_risk(wx: pd.DataFrame, start_month: int, end_month: int, years) -> FrostRisk:
    tmin = wx["tmin_c"].dropna()
    days = pd.DatetimeIndex(tmin.index).normalize().to_numpy().astype("datetime64[D]")
    values = tmin.to_numpy()
    frost = checked = 0
    for year in years:
        first = np.datetime64(planting_date(start_month, end_month, year).date(), "D")
        last = first + np.timedelta64(FROST_WINDOW_DAYS - 1, "D")
        lo, hi = np.searchsorted(days, first), np.searchsorted(days, last, side="right")
        if hi - lo < FROST_WINDOW_DAYS:  # some of the 45 days are missing from the record
            continue
        checked += 1
        if (values[lo:hi] <= FROST_C).any():
            frost += 1
    return FrostRisk(frost, checked)


def note(risk: FrostRisk, block_id: str, crop: str, start_month: int) -> str:
    return (f"Frost occurred within {FROST_WINDOW_DAYS} days of planting in {risk.frost_years} "
            f"of {risk.years} years for block {block_id} ({crop.replace('_', ' ')} planted in "
            f"{MONTH_NAMES[start_month - 1]}).")


def block_notes(blocks, wx: pd.DataFrame, years) -> list[str]:
    """One neutral sentence per annual block whose frost_risk_share is above the limit."""
    out = []
    for b in blocks:
        if b.crop in PERENNIALS:
            continue
        risk = frost_risk(wx, b.start_month, b.end_month, years)
        if risk.above_limit:
            out.append(note(risk, b.id, b.crop, b.start_month))
    return out
