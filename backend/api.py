"""HTTP API for YieldGenerator.

Run with:
    uvicorn backend.api:app --reload

Endpoints:
    GET /api/geocode?q=...          list of {label, lat, lon}
    GET /api/weather?lat=..&lon=..  cached daily POWER data plus FAO-56 ET0
"""

from __future__ import annotations

import math

import requests
from fastapi import FastAPI, HTTPException, Query

from backend import geocode as geocode_mod
from backend import power_client
from backend.et0 import et0_fao56

app = FastAPI(title="YieldGenerator API")


def _clean(values) -> list:
    """JSON has no NaN, so missing values become null."""
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in values]


@app.get("/api/geocode")
def geocode(q: str = Query(..., min_length=1, description="Street address or place name")) -> list[dict]:
    try:
        return geocode_mod.geocode(q)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding service error: {exc}") from exc


@app.get("/api/weather")
def weather(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict:
    """Daily weather for the POWER grid cell containing (lat, lon).

    Response is column oriented to keep it small (about 15k days):
        {"lat", "lon", "elevation_m", "source", "units": {column: unit},
         "dates": ["1984-01-01", ...], "data": {column: [values...]}}
    """
    try:
        df = power_client.get_daily(lat, lon)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"NASA POWER error: {exc}") from exc

    df = df.copy()
    df["et0_mm_day"] = et0_fao56(df).round(3)
    units = {**df.attrs.get("units", power_client.UNITS), "et0_mm_day": "mm/day"}

    return {
        "lat": df.attrs["lat"],
        "lon": df.attrs["lon"],
        "elevation_m": df.attrs.get("elevation_m"),
        "source": "NASA POWER daily point API (community AG); ET0 by FAO-56 Penman-Monteith (pyet)",
        "units": units,
        "dates": df.index.strftime("%Y-%m-%d").tolist(),
        "data": {col: _clean(df[col].tolist()) for col in df.columns},
    }
