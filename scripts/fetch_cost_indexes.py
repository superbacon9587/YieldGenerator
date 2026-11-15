"""Build yearly farm cost indexes from NASS Prices Paid CSVs and the EIA API.

Output: data/prices/cost_indexes.csv with columns
    year, index_name, value, unit, source, source_url

NASS indexes (fertilizer, chemicals, seeds, fuels, wages):
    US annual "INDEX FOR PRICE PAID, 2011" (2011 = 100), read from the Quick Stats
    exports in data/raw/nass_prices_paid/.

electricity:
    California commercial retail electricity price, $/kWh. EIA has no agricultural
    sector, and farm pumping is usually billed on ag tariffs, so commercial is a proxy.
    2001 onward: EIA electricity/retail-sales (cents/kWh, divided by 100).
    Before 2001 (retail-sales has no earlier annual data): EIA State Energy Data
    System series ESCCD ($/million Btu), converted at 3,412 Btu per kWh.

diesel:
    US No 2 diesel retail price, $/gal, EIA annual average (series
    EMD_EPD2D_PTE_NUS_DPG). EIA leaves 1994 blank because the series starts in
    March 1994, so 1994 is the mean of the available monthly values (Apr-Dec;
    March is blank too), and the source column says so.

Requires EIA_API_KEY in .env. The key is never printed: request errors are
re-raised with it redacted. Usage:
    python scripts/fetch_cost_indexes.py
"""

from __future__ import annotations

import csv
import sys
import time

import requests

from _common import PROJECT_ROOT, RAW_DIR, require_env, write_csv

OUTPUT = PROJECT_ROOT / "data" / "prices" / "cost_indexes.csv"
COLUMNS = ["year", "index_name", "value", "unit", "source", "source_url"]

NASS_DIR = RAW_DIR / "nass_prices_paid"
NASS_INDEXES = ["fertilizer", "chemicals", "seeds", "fuels", "wages"]
NASS_SUFFIX = "INDEX FOR PRICE PAID, 2011"
NASS_URL = "https://quickstats.nass.usda.gov"

EIA_BASE = "https://api.eia.gov/v2"
RETRIES = 4
BTU_PER_KWH = 3412
RETAIL_FIRST_YEAR = 2001
FIRST_YEAR = 1990  # match the start of the NASS exports
RETAIL_URL = (
    "https://www.eia.gov/opendata/browser/electricity/retail-sales"
    "?frequency=annual&data=price;&facets=stateid;sectorid;&stateid=CA;&sectorid=COM;"
)
SEDS_URL = (
    "https://www.eia.gov/opendata/browser/seds"
    "?frequency=annual&data=value;&facets=seriesId;stateId;&seriesId=ESCCD;&stateId=CA;"
)
DIESEL_SERIES = "EMD_EPD2D_PTE_NUS_DPG"
DIESEL_URL = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={DIESEL_SERIES}&f=A"


# --- NASS -------------------------------------------------------------------

def read_nass(name: str) -> list[dict]:
    path = NASS_DIR / f"{name}.csv"
    rows = []
    with path.open(newline="") as f:
        for rec in csv.DictReader(f):
            item = rec["Data Item"].strip()
            if rec["Period"].strip() != "YEAR" or not item.endswith(NASS_SUFFIX):
                continue
            value = rec["Value"].replace(",", "").strip()
            try:
                number = float(value)
            except ValueError:
                print(f"WARNING: {name} {rec['Year']}: non-numeric value {value!r}, skipped", file=sys.stderr)
                continue
            rows.append({
                "year": int(rec["Year"]),
                "index_name": name,
                "value": number,
                "unit": "index, 2011=100",
                "source": f"USDA NASS Quick Stats, Prices Paid: {item}, US annual",
                "source_url": NASS_URL,
            })
    if not rows:
        raise SystemExit(f"No annual price-paid index rows found in {path}")
    return rows


# --- EIA --------------------------------------------------------------------

def eia_get(route: str, params: dict, api_key: str) -> list[dict]:
    """Fetch all rows from an EIA v2 data route. Errors never include the key."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = {**params, "api_key": api_key, "offset": offset, "length": 5000}
        for attempt in range(1, RETRIES + 1):
            try:
                resp = requests.get(f"{EIA_BASE}/{route}/data/", params=page, timeout=180)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                message = str(exc).replace(api_key, "***")
                if attempt == RETRIES:
                    raise SystemExit(f"EIA request to {route} failed: {message}") from None
                print(f"EIA request to {route} failed (attempt {attempt}/{RETRIES}), retrying ...", file=sys.stderr)
                time.sleep(5 * attempt)
        body = resp.json()["response"]
        data = body.get("data", [])
        rows.extend(data)
        offset += len(data)
        if not data or offset >= int(body.get("total", 0)):
            return rows


def fetch_electricity(api_key: str) -> list[dict]:
    retail = eia_get(
        "electricity/retail-sales",
        {"frequency": "annual", "data[0]": "price",
         "facets[stateid][]": "CA", "facets[sectorid][]": "COM"},
        api_key,
    )
    out = {}
    for rec in retail:
        if rec.get("price") in (None, ""):
            continue
        if rec["price-units"] != "cents per kilowatt-hour":
            raise SystemExit(f"Unexpected retail-sales unit: {rec['price-units']}")
        year = int(rec["period"])
        out[year] = {
            "year": year,
            "index_name": "electricity",
            "value": round(float(rec["price"]) / 100, 4),
            "unit": "$/kWh",
            "source": "EIA electricity retail-sales, California commercial sector, annual average price",
            "source_url": RETAIL_URL,
        }

    seds = eia_get(
        "seds",
        {"frequency": "annual", "data[0]": "value",
         "facets[stateId][]": "CA", "facets[seriesId][]": "ESCCD",
         "start": str(FIRST_YEAR), "end": str(RETAIL_FIRST_YEAR - 1)},
        api_key,
    )
    for rec in seds:
        year = int(rec["period"])
        if year in out or rec.get("value") in (None, ""):
            continue
        if rec["unit"] != "Dollars per million Btu":
            raise SystemExit(f"Unexpected SEDS unit: {rec['unit']}")
        out[year] = {
            "year": year,
            "index_name": "electricity",
            "value": round(float(rec["value"]) * BTU_PER_KWH / 1e6, 4),
            "unit": "$/kWh",
            "source": "EIA State Energy Data System series ESCCD (California commercial electricity price, "
                      "$/million Btu), converted at 3,412 Btu/kWh",
            "source_url": SEDS_URL,
        }
    return list(out.values())


def fetch_diesel(api_key: str) -> list[dict]:
    base = {"data[0]": "value", "facets[series][]": DIESEL_SERIES}
    annual = eia_get("petroleum/pri/gnd", {**base, "frequency": "annual"}, api_key)
    source = f"EIA US No 2 diesel retail price, series {DIESEL_SERIES}, annual average"
    out = {}
    for rec in annual:
        if rec.get("value") in (None, ""):
            continue
        year = int(rec["period"])
        out[year] = {"year": year, "index_name": "diesel", "value": float(rec["value"]),
                     "unit": "$/gal", "source": source, "source_url": DIESEL_URL}

    # EIA publishes no annual value for 1994 (series starts March 1994).
    if 1994 not in out:
        monthly = eia_get("petroleum/pri/gnd",
                          {**base, "frequency": "monthly", "start": "1994-01", "end": "1994-12"}, api_key)
        values = [float(r["value"]) for r in monthly if r.get("value") not in (None, "")]
        if values:
            out[1994] = {
                "year": 1994, "index_name": "diesel", "value": round(sum(values) / len(values), 4),
                "unit": "$/gal",
                "source": f"EIA US No 2 diesel retail price, series {DIESEL_SERIES}, "
                          f"mean of {len(values)} monthly values (series starts March 1994)",
                "source_url": DIESEL_URL,
            }
    return list(out.values())


def main() -> int:
    rows = []
    for name in NASS_INDEXES:
        rows += read_nass(name)
    api_key = require_env("EIA_API_KEY")
    print("Fetching California electricity prices ...")
    rows += fetch_electricity(api_key)
    print("Fetching US diesel prices ...")
    rows += fetch_diesel(api_key)
    rows.sort(key=lambda r: (r["index_name"], r["year"]))
    write_csv(OUTPUT, COLUMNS, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
