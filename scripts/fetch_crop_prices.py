"""Download California annual "price received" series from USDA NASS Quick Stats.

Output: data/reference/prices/crop_prices.csv with columns crop, year, price, unit, source.
Units are kept exactly as NASS reports them (for example "$ / LB", "$ / TON", "$ / BU").

Requires NASS_API_KEY in .env. Usage:
    python scripts/fetch_crop_prices.py [--start-year 1984]
"""

from __future__ import annotations

import argparse
import sys

import requests

from _common import PRICES_DIR, require_env, write_csv

API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
OUTPUT = PRICES_DIR / "crop_prices.csv"
COLUMNS = ["crop", "year", "price", "unit", "source"]

# crop key -> (commodity_desc used in the query, exact short_desc we keep).
# Pinning short_desc avoids mixing in sibling series (fresh market tomatoes,
# non-alfalfa hay, all-hay, etc.) that come back for the same commodity.
CROPS = {
    "almonds": ("ALMONDS", "ALMONDS - PRICE RECEIVED, MEASURED IN $ / LB"),
    "walnuts": ("WALNUTS", "WALNUTS, ENGLISH - PRICE RECEIVED, MEASURED IN $ / TON"),
    "processing_tomatoes": ("TOMATOES", "TOMATOES, PROCESSING - PRICE RECEIVED, MEASURED IN $ / TON"),
    "corn": ("CORN", "CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU"),
    "oats": ("OATS", "OATS - PRICE RECEIVED, MEASURED IN $ / BU"),
    "alfalfa_hay": ("HAY", "HAY, ALFALFA - PRICE RECEIVED, MEASURED IN $ / TON"),
}

# When NASS publishes more than one annual reference period for the same year,
# prefer the marketing year average and fall back to the calendar year.
PERIOD_PREFERENCE = ["MARKETING YEAR", "YEAR"]


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
        "statisticcat_desc": "PRICE RECEIVED",
        "agg_level_desc": "STATE",
        "state_alpha": "CA",
        "freq_desc": "ANNUAL",
        "year__GE": start_year,
        "format": "JSON",
    }
    resp = requests.get(API_URL, params=params, timeout=120)
    if resp.status_code == 400 and "no data" in resp.text.lower():
        return []
    resp.raise_for_status()
    return resp.json().get("data", [])


def select_rows(crop: str, short_desc: str, records: list[dict]) -> dict[int, dict]:
    """Pick one record per year for the given series, honoring PERIOD_PREFERENCE."""
    by_year: dict[int, dict] = {}
    for rec in records:
        if rec["short_desc"] != short_desc or rec["reference_period_desc"] not in PERIOD_PREFERENCE:
            continue
        if rec.get("domain_desc", "TOTAL") != "TOTAL":
            continue
        year = int(rec["year"])
        current = by_year.get(year)
        rank = PERIOD_PREFERENCE.index(rec["reference_period_desc"])
        if current is None or rank < PERIOD_PREFERENCE.index(current["reference_period_desc"]):
            by_year[year] = rec
    return by_year


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=1984)
    args = parser.parse_args()

    key = require_env("NASS_API_KEY")
    rows: list[dict] = []
    warnings: list[str] = []
    latest_year_overall = args.start_year

    fetched: dict[str, dict[int, dict]] = {}
    for crop, (commodity, short_desc) in CROPS.items():
        print(f"Fetching {crop} ({short_desc}) ...")
        records = fetch_commodity(key, commodity, args.start_year)
        fetched[crop] = select_rows(crop, short_desc, records)
        if fetched[crop]:
            latest_year_overall = max(latest_year_overall, max(fetched[crop]))

    for crop, (_, short_desc) in CROPS.items():
        by_year = fetched[crop]
        if not by_year:
            warnings.append(f"{crop}: no data at all for {args.start_year}-{latest_year_overall}")
            continue
        missing = []
        for year in range(args.start_year, latest_year_overall + 1):
            rec = by_year.get(year)
            value = parse_value(rec["Value"]) if rec else None
            if value is None:
                reason = f" (NASS value {rec['Value'].strip()})" if rec else ""
                missing.append(f"{year}{reason}")
                continue
            rows.append({
                "crop": crop,
                "year": year,
                "price": value,
                "unit": rec["unit_desc"],
                "source": f"USDA NASS Quick Stats: {short_desc}, CA, {rec['reference_period_desc']}",
            })
        if missing:
            warnings.append(f"{crop}: no data for {len(missing)} year(s): {', '.join(missing)}")

    write_csv(OUTPUT, COLUMNS, rows)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
