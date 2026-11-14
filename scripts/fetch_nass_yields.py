"""Download annual Merced County yield per acre from USDA NASS Quick Stats.

Output: data/validation/merced_yields.csv with columns crop, year, yield, unit, source.
Units are kept exactly as NASS reports them (for example "BU / ACRE", "TONS / ACRE").

NASS publishes county level survey estimates mainly for field crops. Tree nuts and
processing tomatoes usually have no county series in Quick Stats (county figures for
those come from the Merced County Agricultural Commissioner crop reports), so expect
warnings for them.

Requires NASS_API_KEY in .env. Usage:
    python scripts/fetch_nass_yields.py [--start-year 1984]
"""

from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

from _common import PROJECT_ROOT, write_csv

API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
OUTPUT = PROJECT_ROOT / "data" / "validation" / "merced_yields.csv"
COLUMNS = ["crop", "year", "yield", "unit", "source"]

# crop key (matches crop_prices.csv) -> (commodity_desc for the query, short_desc
# prefix we keep). The prefix pins the series (grain corn, not silage; alfalfa hay,
# not all hay) without hard coding the unit NASS uses.
CROPS = {
    "almonds": ("ALMONDS", "ALMONDS - YIELD"),
    "walnuts": ("WALNUTS", "WALNUTS, ENGLISH - YIELD"),
    "processing_tomatoes": ("TOMATOES", "TOMATOES, PROCESSING - YIELD"),
    "corn": ("CORN", "CORN, GRAIN - YIELD"),
    "oats": ("OATS", "OATS - YIELD"),
    "alfalfa_hay": ("HAY", "HAY, ALFALFA - YIELD"),
}


def parse_value(raw: str) -> float | None:
    """NASS values are strings like "1,234.5"; suppressed values look like "(D)" or "(NA)"."""
    raw = raw.strip().replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_commodity(key: str, commodity: str, start_year: int) -> list[dict]:
    params = {
        "key": key,
        "commodity_desc": commodity,
        "statisticcat_desc": "YIELD",
        "agg_level_desc": "COUNTY",
        "state_alpha": "CA",
        "county_name": "MERCED",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "year__GE": start_year,
        "format": "JSON",
    }
    resp = requests.get(API_URL, params=params, timeout=120)
    # Quick Stats answers 400 "invalid query" (not an empty list) when a filter
    # value such as county_name has no records for this commodity.
    if resp.status_code == 400 and any(s in resp.text.lower() for s in ("no data", "invalid query")):
        return []
    if not resp.ok:
        # Not raise_for_status(): its message includes the URL, which contains the API key.
        raise SystemExit(f"NASS request for {commodity} failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json().get("data", [])


def select_rows(prefix: str, records: list[dict]) -> dict[int, dict]:
    """One record per year: the TOTAL domain survey value for the pinned series.
    If NASS returns the series in more than one unit, keep the first unit seen."""
    by_year: dict[int, dict] = {}
    unit = None
    for rec in records:
        if not rec["short_desc"].startswith(prefix + ","):
            continue
        if rec.get("domain_desc", "TOTAL") != "TOTAL" or rec.get("source_desc") != "SURVEY":
            continue
        if parse_value(rec["Value"]) is None:
            continue
        unit = unit or rec["unit_desc"]
        if rec["unit_desc"] != unit:
            continue
        by_year.setdefault(int(rec["year"]), rec)
    return by_year


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=1984)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("NASS_API_KEY", "").strip()
    if not key:
        raise SystemExit(f"Missing NASS_API_KEY. Add it to {PROJECT_ROOT / '.env'}.")

    rows: list[dict] = []
    warnings: list[str] = []
    for crop, (commodity, prefix) in CROPS.items():
        print(f"Fetching {crop} ({prefix}) ...")
        by_year = select_rows(prefix, fetch_commodity(key, commodity, args.start_year))
        if not by_year:
            warnings.append(f"{crop}: no Merced County yield data in NASS Quick Stats")
            continue
        for year in sorted(by_year):
            rec = by_year[year]
            rows.append({
                "crop": crop,
                "year": year,
                "yield": parse_value(rec["Value"]),
                "unit": rec["unit_desc"],
                "source": f"USDA NASS Quick Stats: {rec['short_desc']}, Merced County CA, {rec['source_desc']}",
            })
        print(f"  {len(by_year)} years ({min(by_year)}-{max(by_year)})")

    write_csv(OUTPUT, COLUMNS, rows)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
