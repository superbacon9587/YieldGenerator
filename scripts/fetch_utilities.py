"""Download California electricity and diesel prices from the EIA API v2.

Output: data/reference/prices/utilities.csv with columns type, year, price, unit, source.

  electricity_commercial / electricity_industrial:
      EIA annual average retail price, units as reported (cents per kilowatt-hour).
  diesel:
      EIA monthly California No 2 diesel retail price ($/GAL), averaged to calendar
      years. Only years with all 12 months are written; partial years are skipped
      with a warning so a half year is never mistaken for an annual average.

Note: EIA has no agricultural sector. Farm pumping is usually billed on utility
ag tariffs, so commercial or industrial prices are a proxy.

Requires EIA_API_KEY in .env. Usage:
    python scripts/fetch_utilities.py
"""

from __future__ import annotations

import sys
from collections import defaultdict

import requests

from _common import PRICES_DIR, require_env, write_csv

BASE_URL = "https://api.eia.gov/v2"
OUTPUT = PRICES_DIR / "utilities.csv"
COLUMNS = ["type", "year", "price", "unit", "source"]

ELECTRICITY_SECTORS = {"COM": "electricity_commercial", "IND": "electricity_industrial"}
DIESEL_SERIES = "EMD_EPD2D_PTE_SCA_DPG"  # California No 2 Diesel Retail Prices, $/GAL


def eia_get(route: str, params: dict, api_key: str) -> list[dict]:
    """Fetch all rows from an EIA v2 data route, following offset pagination."""
    rows: list[dict] = []
    offset = 0
    while True:
        page_params = {**params, "api_key": api_key, "offset": offset, "length": 5000}
        resp = requests.get(f"{BASE_URL}/{route}/data/", params=page_params, timeout=180)
        resp.raise_for_status()
        body = resp.json()["response"]
        data = body.get("data", [])
        rows.extend(data)
        offset += len(data)
        if not data or offset >= int(body.get("total", 0)):
            return rows


def fetch_electricity(api_key: str) -> list[dict]:
    records = eia_get(
        "electricity/retail-sales",
        {
            "frequency": "annual",
            "data[0]": "price",
            "facets[stateid][]": "CA",
            "facets[sectorid][]": list(ELECTRICITY_SECTORS),
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
        },
        api_key,
    )
    out = []
    for rec in records:
        if rec.get("price") in (None, ""):
            print(f"WARNING: electricity {rec['sectorid']} {rec['period']}: no price", file=sys.stderr)
            continue
        out.append({
            "type": ELECTRICITY_SECTORS[rec["sectorid"]],
            "year": int(rec["period"]),
            "price": float(rec["price"]),
            "unit": rec["price-units"],
            "source": f"EIA API v2 electricity/retail-sales, CA, sector {rec['sectorid']}, annual",
        })
    return out


def fetch_diesel(api_key: str) -> list[dict]:
    records = eia_get(
        "petroleum/pri/gnd",
        {
            "frequency": "monthly",
            "data[0]": "value",
            "facets[series][]": DIESEL_SERIES,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
        },
        api_key,
    )
    by_year: dict[int, list[float]] = defaultdict(list)
    units = set()
    for rec in records:
        if rec.get("value") in (None, ""):
            continue
        by_year[int(rec["period"][:4])].append(float(rec["value"]))
        units.add(rec["units"])
    if len(units) > 1:
        raise SystemExit(f"Diesel series returned mixed units: {units}")
    unit = units.pop() if units else "$/GAL"

    out = []
    for year in sorted(by_year):
        months = by_year[year]
        if len(months) < 12:
            print(f"WARNING: diesel {year}: only {len(months)} month(s) of data, skipped", file=sys.stderr)
            continue
        out.append({
            "type": "diesel",
            "year": year,
            "price": round(sum(months) / len(months), 4),
            "unit": unit,
            "source": f"EIA API v2 petroleum/pri/gnd series {DIESEL_SERIES}, mean of 12 monthly values",
        })
    return out


def main() -> int:
    api_key = require_env("EIA_API_KEY")
    print("Fetching California electricity prices ...")
    rows = fetch_electricity(api_key)
    print("Fetching California diesel prices ...")
    rows += fetch_diesel(api_key)
    rows.sort(key=lambda r: (r["type"], r["year"]))
    write_csv(OUTPUT, COLUMNS, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
