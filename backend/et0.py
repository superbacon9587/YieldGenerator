"""Daily FAO-56 Penman-Monteith reference evapotranspiration (ET0) via pyet.

Inputs come from the POWER DataFrame returned by backend.power_client.get_daily().
Choices, following FAO-56 (Allen et al. 1998):
    Tmean        (Tmax + Tmin) / 2 (eq. 9), not POWER's 24 h mean T2M
    es           mean of e0(Tmax) and e0(Tmin) (eq. 12)
    ea           from mean relative humidity (eq. 19), since POWER gives RH2M only
    gamma        from POWER surface pressure (eq. 8)
    Rso          (0.75 + 2e-5 z) Ra (eq. 37), z = POWER grid cell elevation
    G            0 for daily steps (eq. 42)
"""

from __future__ import annotations

import math

import pandas as pd
import pyet

REQUIRED_COLUMNS = ["tmax_c", "tmin_c", "rh_pct", "wind_2m_m_s", "solar_mj_m2_day", "pressure_kpa"]


def et0_fao56(df: pd.DataFrame, lat: float | None = None,
              elevation_m: float | None = None) -> pd.Series:
    """Reference ET0 in mm/day, indexed like df. Days with missing inputs give NaN.

    lat and elevation_m default to df.attrs["lat"] and df.attrs["elevation_m"].
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing columns: {missing}")
    lat = df.attrs.get("lat") if lat is None else lat
    elevation_m = df.attrs.get("elevation_m") if elevation_m is None else elevation_m
    if lat is None or elevation_m is None:
        raise ValueError("lat and elevation_m are required (pass them or set df.attrs)")

    # pyet sanity checks RH with nanmax and raises when every value is NaN.
    if df["rh_pct"].isna().all():
        return pd.Series(float("nan"), index=df.index, name="et0_mm_day")

    tmax, tmin = df["tmax_c"], df["tmin_c"]
    et0 = pyet.pm_fao56(
        tmean=(tmax + tmin) / 2,
        wind=df["wind_2m_m_s"],
        rs=df["solar_mj_m2_day"],
        tmax=tmax,
        tmin=tmin,
        rh=df["rh_pct"],
        pressure=df["pressure_kpa"],
        elevation=elevation_m,
        lat=math.radians(lat),
    )
    return pd.Series(et0, index=df.index, name="et0_mm_day")
