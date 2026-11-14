"""Daily weather from the NASA POWER point API (community AG).

Main entry points:
    snap_to_grid()   nearest POWER meteorology grid center (0.5 deg lat x 0.625 deg lon)
    get_daily()      daily DataFrame for a lat/lon, served from the parquet cache when present

One request covers 1984-01-01 through December 31 of last year. The cache file is
data/cache/power/{lat}_{lon}.parquet using the snapped coordinates, so every point
inside the same grid cell shares one file. A cached file that ends before the
expected end date (for example after New Year) is refetched.

The returned DataFrame is indexed by date (named "date") and carries metadata in
df.attrs: lat, lon (snapped), elevation_m (POWER grid cell elevation), and units.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "power"

API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
START_DATE = dt.date(1984, 1, 1)
FILL_VALUE = -999.0

GRID_LAT_STEP = 0.5
GRID_LON_STEP = 0.625

# POWER parameter -> (our column name, unit we return).
PARAMETERS = {
    "T2M": ("tmean_c", "degC"),
    "T2M_MAX": ("tmax_c", "degC"),
    "T2M_MIN": ("tmin_c", "degC"),
    "RH2M": ("rh_pct", "%"),
    "WS2M": ("wind_2m_m_s", "m/s"),
    "ALLSKY_SFC_SW_DWN": ("solar_mj_m2_day", "MJ/m^2/day"),
    "PRECTOTCORR": ("precip_mm_day", "mm/day"),
    "PS": ("pressure_kpa", "kPa"),
    "GWETPROF": ("root_zone_wetness_frac", "fraction (0 to 1)"),
}

# Units POWER reports for each parameter with community=AG. A mismatch means the
# API changed and the column would be mislabeled, so we fail loudly instead.
EXPECTED_POWER_UNITS = {
    "T2M": "C", "T2M_MAX": "C", "T2M_MIN": "C",
    "RH2M": "%", "WS2M": "m/s", "ALLSKY_SFC_SW_DWN": "MJ/m^2/day",
    "PRECTOTCORR": "mm/day", "PS": "kPa", "GWETPROF": "1",
}

COLUMNS = [name for name, _ in PARAMETERS.values()]
UNITS = {name: unit for name, unit in PARAMETERS.values()}


def snap_to_grid(lat: float, lon: float) -> tuple[float, float]:
    """Nearest POWER grid center. Latitude centers are multiples of 0.5 deg,
    longitude centers are -180 + k * 0.625 deg (equivalently multiples of 0.625)."""
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude out of range: {lat}")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude out of range: {lon}")
    snapped_lat = round(lat / GRID_LAT_STEP) * GRID_LAT_STEP
    snapped_lon = round(lon / GRID_LON_STEP) * GRID_LON_STEP
    if snapped_lon >= 180:  # 180 and -180 are the same meridian
        snapped_lon -= 360
    # Round to kill float noise such as 37.50000000001 before it reaches a filename.
    return round(snapped_lat, 4) + 0.0, round(snapped_lon, 4) + 0.0


def default_end_date(today: dt.date | None = None) -> dt.date:
    """December 31 of last year."""
    today = today or dt.date.today()
    return dt.date(today.year - 1, 12, 31)


def cache_path(lat: float, lon: float) -> Path:
    """Cache file for an already snapped lat/lon."""
    return CACHE_DIR / f"{lat:g}_{lon:g}.parquet"


def fetch_power_json(lat: float, lon: float, start: dt.date, end: dt.date,
                     timeout: float = 180) -> dict:
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    resp = requests.get(API_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_power_json(payload: dict) -> pd.DataFrame:
    """Turn a POWER daily point JSON response into a tidy DataFrame."""
    param_data = payload["properties"]["parameter"]
    missing = [p for p in PARAMETERS if p not in param_data]
    if missing:
        raise ValueError(f"POWER response is missing parameters: {missing}")

    reported_units = payload.get("parameters", {})
    for p, expected in EXPECTED_POWER_UNITS.items():
        got = reported_units.get(p, {}).get("units")
        if got is not None and got != expected:
            raise ValueError(f"POWER returned {p} in {got!r}, expected {expected!r}")

    fill = payload.get("header", {}).get("fill_value", FILL_VALUE)
    df = pd.DataFrame({PARAMETERS[p][0]: pd.Series(param_data[p], dtype="float64")
                       for p in PARAMETERS})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.sort_index()[COLUMNS]
    df = df.mask(np.isclose(df, fill) | np.isclose(df, FILL_VALUE))

    coords = payload.get("geometry", {}).get("coordinates", [])
    df.attrs = {
        "lon": float(coords[0]) if len(coords) > 0 else None,
        "lat": float(coords[1]) if len(coords) > 1 else None,
        "elevation_m": float(coords[2]) if len(coords) > 2 else None,
        "units": dict(UNITS),
        "source": "NASA POWER daily point API, community AG",
    }
    return df


def get_daily(lat: float, lon: float, refresh: bool = False,
              today: dt.date | None = None) -> pd.DataFrame:
    """Daily POWER data for the grid cell containing (lat, lon).

    Loads data/cache/power/{lat}_{lon}.parquet when it exists and reaches the
    expected end date; otherwise downloads the full record in one request and
    writes the cache.
    """
    slat, slon = snap_to_grid(lat, lon)
    end = default_end_date(today)
    path = cache_path(slat, slon)

    if path.exists() and not refresh:
        df = pd.read_parquet(path)
        if len(df) and df.index.max().date() >= end:
            return _finish(df, slat, slon)

    df = parse_power_json(fetch_power_json(slat, slon, START_DATE, end))
    df = _finish(df, slat, slon)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def _finish(df: pd.DataFrame, slat: float, slon: float) -> pd.DataFrame:
    """Make sure attrs always carry the snapped coordinates and units."""
    attrs = dict(df.attrs)
    attrs["lat"], attrs["lon"] = slat, slon
    attrs.setdefault("units", dict(UNITS))
    df.attrs = attrs
    return df
