"""Turn coordinates into a US state and county with the US Census Geocoder.

lookup(lat, lon) returns {"state": "CA", "county": "Merced", "in_california": True}.
Points outside the US (or offshore) come back as
{"state": None, "county": None, "in_california": False}.

Results are cached in memory per process, keyed on coordinates rounded to 5 decimal
places (about 1 m). Network errors raise requests.RequestException and are not cached.
"""

from __future__ import annotations

from functools import lru_cache

import requests

CENSUS_COORDS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
TIMEOUT = 20


def fetch_geographies(lat: float, lon: float) -> dict:
    """Raw "geographies" object from the Census Geocoder for one point."""
    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "States,Counties",
        "format": "json",
    }
    resp = requests.get(CENSUS_COORDS_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("result", {}).get("geographies", {}) or {}


def parse_geographies(geos: dict) -> dict:
    states = geos.get("States") or []
    counties = geos.get("Counties") or []
    state = states[0].get("STUSAB") if states else None
    county = None
    if counties:
        c = counties[0]
        county = c.get("BASENAME") or (c.get("NAME") or "").removesuffix(" County") or None
    return {"state": state, "county": county, "in_california": state == "CA"}


@lru_cache(maxsize=4096)
def _lookup_rounded(lat: float, lon: float) -> tuple:
    r = parse_geographies(fetch_geographies(lat, lon))
    return r["state"], r["county"], r["in_california"]


def lookup(lat: float, lon: float) -> dict:
    state, county, in_ca = _lookup_rounded(round(lat, 5), round(lon, 5))
    return {"state": state, "county": county, "in_california": in_ca}


def clear_cache() -> None:
    _lookup_rounded.cache_clear()
