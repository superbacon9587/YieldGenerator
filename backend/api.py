"""HTTP API for YieldGenerator.

Run with:
    uvicorn backend.api:app --reload

Endpoints:
    GET /api/geocode?q=...          list of {label, lat, lon}
    GET /api/weather?lat=..&lon=..  cached daily POWER data plus FAO-56 ET0
    GET /api/context?lat=..&lon=..  county, cost region, baseline yields, costs, water price
    POST /api/simulate              farm backtest (docs/api_contract.md)
    GET /api/meta                   first and last backtest years, period presets
    POST /api/compare               rank 2 to 6 saved farm setups
    POST /api/optimize              best crop plan within land, budget, and water
"""

from __future__ import annotations

import math

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend import geocode as geocode_mod
from backend import power_client, regions
from backend import simulate as simulate_mod
from backend.et0 import et0_fao56
from backend import compare as compare_mod
from backend.schemas import (
    CompareRequest,
    CompareResponse,
    MetaResponse,
    SimulateRequest,
    SimulateResponse,
)

app = FastAPI(title="YieldGenerator API")

# The Vite dev server runs on 5173; allow it to call the API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
# Calculation records make simulate responses large; compress them.
app.add_middleware(GZipMiddleware, minimum_size=1000)


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


@app.get("/api/context")
def context(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict:
    """State, county, cost region, baseline yields, production costs and water price
    for a point. Shape is documented in backend/regions.py."""
    try:
        return regions.get_location_context(lat, lon)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Census Geocoder error: {exc}") from exc


@app.post("/api/simulate", response_model=SimulateResponse)
def simulate(req: SimulateRequest) -> SimulateResponse:
    """Backtest a farm over the requested years. Contract: docs/api_contract.md."""
    try:
        return simulate_mod.simulate(req)
    except simulate_mod.WeatherUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Data service error: {exc}") from exc


PERIOD_PRESETS = (5, 10, 20, 30, 40)


@app.get("/api/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    """Backtest year range and the period presets that fit inside it.

    first_year is the first full year with weather for every season: POWER
    daily data starts in 1984, and a season that wraps the new year needs the
    previous year, so 1985 is the first year any block can use.
    """
    first = power_client.START_DATE.year + 1
    last = power_client.default_end_date().year
    span = last - first + 1
    return MetaResponse(first_year=first, last_full_year=last,
                        presets=[p for p in PERIOD_PRESETS if p <= span])


@app.post("/api/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    """Run 2 to 6 farm setups and rank them by one summary number."""
    try:
        return compare_mod.compare(req)
    except simulate_mod.WeatherUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Data service error: {exc}") from exc


# ---------------------------------------------------------------- optimize (Part C, iteration 2)

from backend import optimize as optimize_mod  # noqa: E402
from backend.schemas import OptimizeRequest, OptimizeResponse  # noqa: E402


@app.post("/api/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest) -> OptimizeResponse:
    """Best crop plan for the farm's land, budget, and water. Contract: docs/api_contract.md."""
    try:
        return optimize_mod.optimize(req)
    except simulate_mod.WeatherUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Data service error: {exc}") from exc
