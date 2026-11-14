"""Download annual California yield per acre (county and state) from USDA NASS Quick Stats.

Outputs:
    data/validation/ca_county_yields.csv  columns county, crop, year, yield, unit, source
    data/validation/ca_state_yields.csv   columns crop, year, yield, unit, source

Units are kept exactly as NASS reports them (for example "BU / ACRE", "TONS / ACRE").
Only final annual survey estimates are kept (reference period YEAR, domain TOTAL);
monthly forecasts and Census of Agriculture figures are dropped.

Coverage notes (as of the 2026 Quick Stats data):
  * NASS publishes no California county yield series for almonds, walnuts, or alfalfa
    hay, so those crops appear only in the state file. County figures for them live in
    the County Agricultural Commissioner crop reports.
  * County estimates exclude the "OTHER (COMBINED) COUNTIES" bucket (county code 998).

This script does not touch data/validation/merced_yields.csv; that file is still
produced by scripts/fetch_nass_yields.py.

Requires NASS_API_KEY in .env. Usage:
    python scripts/fetch_ca_yields.py [--start-year 1984] [--min-years 10]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import requests

from _common import PROJECT_ROOT, require_env, write_csv

API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
VALIDATION_DIR = PROJECT_ROOT / "data" / "validation"
COUNTY_OUTPUT = VALIDATION_DIR / "ca_county_yields.csv"
STATE_OUTPUT = VALIDATION_DIR / "ca_state_yields.csv"
COUNTY_COLUMNS = ["county", "crop", "year", "yield", "unit", "source"]
STATE_COLUMNS = ["crop", "year", "yield", "unit", "source"]
OTHER_COUNTIES_CODE = "998"

# crop key (matches crop_prices.csv) -> (NASS commodity_desc, accepted short_desc values
# in priority order). The NASS commodity name differs from our key for some crops
# (processing tomatoes live under TOMATOES, alfalfa under HAY), and some series were
# renamed over time (almonds switched to "ALMONDS, UTILIZED" from 2018 on). For each
# year the first listed series that has a value wins. Pinning the full short_desc also
# pins the unit (BU / ACRE, not BU / NET PLANTED ACRE) and excludes look alike series
# such as corn silage or fresh market tomatoes.
SERIES: dict[str, tuple[str, list[str]]] = {
    "almonds": ("ALMONDS", [
        "ALMONDS, UTILIZED, SHELLED - YIELD, MEASURED IN LB / ACRE",
        "ALMONDS, UTILIZED - YIELD, MEASURED IN LB / ACRE",
    ]),
    "walnuts": ("WALNUTS", [
        "WALNUTS, ENGLISH, UTILIZED, IN SHELL - YIELD, MEASURED IN TONS / ACRE",
        "WALNUTS, ENGLISH - YIELD, MEASURED IN TONS / ACRE",
    ]),
    "processing_tomatoes": ("TOMATOES", [
        "TOMATOES, IN THE OPEN, PROCESSING - YIELD, MEASURED IN TONS / ACRE",
        "TOMATOES, PROCESSING - YIELD, MEASURED IN TONS / ACRE",
    ]),
    "corn": ("CORN", ["CORN, GRAIN - YIELD, MEASURED IN BU / ACRE"]),
    "oats": ("OATS", ["OATS - YIELD, MEASURED IN BU / ACRE"]),
    "alfalfa_hay": ("HAY", ["HAY, ALFALFA - YIELD, MEASURED IN TONS / ACRE"]),
}


def parse_value(raw: str) -> float | None:
    """NASS values are strings like "1,234.5"; suppressed values look like "(D)" or "(NA)"."""
    try:
        return float(raw.strip().replace(",", ""))
    except ValueError:
        return None


def fetch(key: str, commodity: str, agg_level: str, start_year: int) -> list[dict]:
    """One request per commodity and aggregation level keeps each response well under
    the Quick Stats 50,000 row limit."""
    params = {
        "key": key,
        "commodity_desc": commodity,
        "statisticcat_desc": "YIELD",
        "agg_level_desc": agg_level,
        "state_alpha": "CA",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "source_desc": "SURVEY",
        "domain_desc": "TOTAL",
        "year__GE": start_year,
        "format": "JSON",
    }
    resp = requests.get(API_URL, params=params, timeout=180)
    # Quick Stats answers 400 "invalid query" (not an empty list) when nothing matches.
    if resp.status_code == 400 and any(s in resp.text.lower() for s in ("no data", "invalid query")):
        return []
    if not resp.ok:
        # Not raise_for_status(): its message includes the URL, which contains the API key.
        raise SystemExit(f"NASS {agg_level} request for {commodity} failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json().get("data", [])


def select(records: list[dict], series: list[str], by_county: bool) -> dict[tuple, dict]:
    """Pick one record per (county, year) or per year, honoring the series priority."""
    rank = {name: i for i, name in enumerate(series)}
    chosen: dict[tuple, dict] = {}
    for rec in records:
        if rec["short_desc"] not in rank or parse_value(rec["Value"]) is None:
            continue
        if by_county:
            if rec.get("county_code") == OTHER_COUNTIES_CODE or not rec.get("county_name"):
                continue
            k = (rec["county_name"].title(), int(rec["year"]))
        else:
            k = (int(rec["year"]),)
        if k not in chosen or rank[rec["short_desc"]] < rank[chosen[k]["short_desc"]]:
            chosen[k] = rec
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=1984)
    parser.add_argument("--min-years", type=int, default=10, help="threshold for the coverage summary")
    args = parser.parse_args()
    key = require_env("NASS_API_KEY")

    county_rows: list[dict] = []
    state_rows: list[dict] = []
    years_per_county: dict[str, dict[str, int]] = {}
    state_span: dict[str, str] = {}

    for crop, (commodity, series) in SERIES.items():
        print(f"Fetching {crop} (NASS commodity {commodity}) ...")

        county = select(fetch(key, commodity, "COUNTY", args.start_year), series, by_county=True)
        counts: dict[str, int] = defaultdict(int)
        for (name, year), rec in sorted(county.items()):
            counts[name] += 1
            county_rows.append({
                "county": name,
                "crop": crop,
                "year": year,
                "yield": parse_value(rec["Value"]),
                "unit": rec["unit_desc"],
                "source": f"USDA NASS Quick Stats: {rec['short_desc']}, {name} County CA, SURVEY",
            })
        years_per_county[crop] = dict(counts)

        state = select(fetch(key, commodity, "STATE", args.start_year), series, by_county=False)
        for (year,), rec in sorted(state.items()):
            state_rows.append({
                "crop": crop,
                "year": year,
                "yield": parse_value(rec["Value"]),
                "unit": rec["unit_desc"],
                "source": f"USDA NASS Quick Stats: {rec['short_desc']}, California, SURVEY",
            })
        years = [y for (y,) in state]
        state_span[crop] = f"{len(years)} yrs, {min(years)}-{max(years)}" if years else "none"

    write_csv(COUNTY_OUTPUT, COUNTY_COLUMNS, county_rows)
    write_csv(STATE_OUTPUT, STATE_COLUMNS, state_rows)

    print(f"\nCoverage summary (counties with {args.min_years}+ years of NASS county yield data)")
    print(f"{'crop':<22}{'counties >= ' + str(args.min_years):>16}{'counties any':>15}  {'county years':<14}{'state series'}")
    for crop in SERIES:
        counts = years_per_county[crop]
        well = sum(1 for n in counts.values() if n >= args.min_years)
        crop_years = [r["year"] for r in county_rows if r["crop"] == crop]
        span = f"{min(crop_years)}-{max(crop_years)}" if crop_years else "none"
        print(f"{crop:<22}{well:>16}{len(counts):>15}  {span:<14}{state_span[crop]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
