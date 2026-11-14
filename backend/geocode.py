"""Turn a free text location into coordinates.

US street addresses go to the US Census Geocoder. City names (or anything the
Census Geocoder cannot match) go to the Open-Meteo Geocoding API.

geocode(q) returns a list of {"label": str, "lat": float, "lon": float}, best match first.
"""

from __future__ import annotations

import re

import requests

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 20

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def looks_like_street_address(q: str) -> bool:
    """Street addresses start with a house number, e.g. "1234 Main St, Merced, CA"."""
    return bool(re.match(r"^\s*\d+[A-Za-z]?\s+\S", q))


def census_geocode(q: str) -> list[dict]:
    params = {"address": q, "benchmark": "Public_AR_Current", "format": "json"}
    resp = requests.get(CENSUS_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    matches = resp.json().get("result", {}).get("addressMatches", [])
    return [
        {"label": m["matchedAddress"], "lat": float(m["coordinates"]["y"]),
         "lon": float(m["coordinates"]["x"])}
        for m in matches
    ]


def _matches_qualifier(result: dict, qualifier: str) -> bool:
    """Does an Open-Meteo result match a trailing qualifier such as "CA" or "California"?"""
    q = qualifier.strip().lower()
    q_full = US_STATES.get(qualifier.strip().upper(), "").lower()
    fields = [result.get(k, "") or "" for k in ("admin1", "admin2", "country", "country_code")]
    fields = [f.lower() for f in fields]
    return q in fields or (q_full and q_full in fields) or (q in ("usa", "us") and "us" in fields)


def open_meteo_geocode(q: str, count: int = 10) -> list[dict]:
    """Open-Meteo matches on a place name only, so "Merced, CA" is searched as
    "Merced" and the trailing parts are used to filter and rank the results."""
    parts = [p.strip() for p in q.split(",") if p.strip()]
    if not parts:
        return []
    name, qualifiers = parts[0], parts[1:]
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results", []) or []
    if qualifiers:
        filtered = [r for r in results if all(_matches_qualifier(r, x) for x in qualifiers)]
        results = filtered or results

    out = []
    for r in results:
        label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        out.append({"label": label, "lat": float(r["latitude"]), "lon": float(r["longitude"])})
    return out


def geocode(q: str) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    if looks_like_street_address(q):
        results = census_geocode(q)
        if results:
            return results
    return open_meteo_geocode(q)
