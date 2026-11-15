"""Location context: what YieldGenerator knows about a point in California.

get_location_context(lat, lon) returns exactly this shape (the simulation engine
depends on it, so do not add or rename keys):

    {
      "state": "CA",
      "county": "Merced",
      "in_california": True,
      "cost_region": "San Joaquin Valley North",
      "baseline_yields": {crop: {"value", "unit", "basis": "county" | "state", "source"}},
      "production_costs": {crop: {"cost_excl_water", "unit": "$ / ACRE", "region", "source"}},
      "surface_water_price_per_af": float,
      "data_quality": [plain English notes],
    }

Rules:
  * baseline_yields: median NASS county yield when the county has at least
    MIN_COUNTY_YEARS years of data (basis "county"), otherwise the median California
    statewide yield (basis "state").
  * production_costs: the latest UC Davis cost study for the point's cost region,
    otherwise the nearest region with a study (order in ca_regions.json), otherwise
    San Joaquin Valley North. Statewide and organic studies are not used.
  * A crop with no data anywhere is left out and explained in data_quality.
  * Points outside California (state, county and cost_region may be None) get
    California statewide yields, San Joaquin Valley North costs and water price, and
    a warning.

Data files: data/validation/ca_county_yields.csv, data/validation/ca_state_yields.csv,
data/reference/prices/production_costs.csv, data/reference/prices/defaults.json,
data/reference/ca_regions.json.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from statistics import median

from backend import county_lookup, reference

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
VALIDATION_DIR = DATA_DIR / "validation"
PRICES_DIR = DATA_DIR / "reference" / "prices"
REGIONS_FILE = DATA_DIR / "reference" / "ca_regions.json"

MIN_COUNTY_YEARS = 10
DEFAULT_REGION = "San Joaquin Valley North"
COST_UNIT = "$ / ACRE"
OUTSIDE_CA_NOTE = (
    "Location is outside California. Water and yield use NASA data for this location, "
    "but dollar values use California prices and costs, so they are rough estimates."
)
CROP_LABELS = {
    "almonds": "Almond",
    "walnuts": "Walnut",
    "processing_tomatoes": "Processing tomato",
    "corn": "Corn",
    "oats": "Oat",
    "alfalfa_hay": "Alfalfa hay",
}


@dataclass
class Tables:
    """Everything get_location_context reads from disk, loaded once."""
    county_yields: dict[tuple[str, str], list[tuple[int, float, str]]]   # (county, crop) -> [(year, yield, unit)]
    state_yields: dict[str, list[tuple[int, float, str]]]                 # crop -> [(year, yield, unit)]
    costs: dict[tuple[str, str], dict]                                     # (crop, region) -> latest study row
    county_region: dict[str, str]
    nearest_regions: dict[str, list[str]]
    water_price: dict = field(default_factory=dict)                        # defaults.json surface_water_price_per_af


def _read_yields(path: Path, by_county: bool) -> dict:
    out: dict = defaultdict(list)
    if not path.exists():
        return out
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if not r["yield"]:
                continue
            key = (r["county"], r["crop"]) if by_county else r["crop"]
            out[key].append((int(r["year"]), float(r["yield"]), r["unit"]))
    return out


def _read_costs(path: Path, regions: list[str]) -> dict[tuple[str, str], dict]:
    """Latest study per (crop, region), conventional regional studies only."""
    best: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return best
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["region"] not in regions or not r["cost_excl_water"] or not r["study_year"]:
                continue
            key = (r["crop"], r["region"])
            if key not in best or int(r["study_year"]) > int(best[key]["study_year"]):
                best[key] = r
    return best


def load_tables(
    county_csv: Path = VALIDATION_DIR / "ca_county_yields.csv",
    state_csv: Path = VALIDATION_DIR / "ca_state_yields.csv",
    costs_csv: Path = PRICES_DIR / "production_costs.csv",
    defaults_json: Path = PRICES_DIR / "defaults.json",
    regions_json: Path = REGIONS_FILE,
) -> Tables:
    regions = json.loads(Path(regions_json).read_text())
    defaults = json.loads(Path(defaults_json).read_text())
    return Tables(
        county_yields=_read_yields(Path(county_csv), by_county=True),
        state_yields=_read_yields(Path(state_csv), by_county=False),
        costs=_read_costs(Path(costs_csv), regions["regions"]),
        county_region=regions["counties"],
        nearest_regions=regions["nearest_regions"],
        water_price=defaults.get("surface_water_price_per_af", {}),
    )


@cache
def _default_tables() -> Tables:
    return load_tables()


def _span(rows: list[tuple[int, float, str]]) -> str:
    years = sorted(y for y, _, _ in rows)
    return f"median of {len(years)} years, {years[0]}-{years[-1]}"


def _baseline_yields(t: Tables, county: str | None, in_ca: bool, crops: list[str], notes: list[str]) -> dict:
    out = {}
    for crop in crops:
        label = CROP_LABELS.get(crop, crop)
        county_rows = t.county_yields.get((county, crop), []) if (in_ca and county) else []
        state_rows = t.state_yields.get(crop, [])
        if len(county_rows) >= MIN_COUNTY_YEARS:
            out[crop] = {
                "value": round(median(v for _, v, _ in county_rows), 3),
                "unit": county_rows[0][2],
                "basis": "county",
                "source": f"USDA NASS Quick Stats survey yield, {county} County CA, {_span(county_rows)}",
            }
            continue
        if state_rows:
            out[crop] = {
                "value": round(median(v for _, v, _ in state_rows), 3),
                "unit": state_rows[0][2],
                "basis": "state",
                "source": f"USDA NASS Quick Stats survey yield, California statewide, {_span(state_rows)}",
            }
            if in_ca:
                why = (f"only {len(county_rows)} years of county data for {county}" if county_rows
                       else f"no county data for {county}")
                notes.append(f"{label} yield uses the statewide median ({why}).")
            continue
        notes.append(f"No NASS yield data for {label.lower()} anywhere in California, so it has no baseline yield.")
    return out


def _production_costs(t: Tables, region: str | None, crops: list[str], notes: list[str]) -> dict:
    out = {}
    order = ([region] + t.nearest_regions.get(region, [])) if region else []
    if DEFAULT_REGION not in order:
        order.append(DEFAULT_REGION)
    # Any other region with a study is better than leaving the crop out.
    order += [r for r in t.nearest_regions if r not in order]
    for crop in crops:
        label = CROP_LABELS.get(crop, crop)
        used = next((r for r in order if (crop, r) in t.costs), None)
        if used is None:
            notes.append(f"No production cost study for {label.lower()} in any region, so it has no production cost.")
            continue
        row = t.costs[(crop, used)]
        source = f"UC Davis cost study {row['source']} ({row['study_year']}, {used})"
        if region and used != region:
            source += f"; used because {region} has no {label.lower()} study"
            notes.append(f"{label} production cost uses the {used} study (no study for {region}).")
        out[crop] = {
            "cost_excl_water": float(row["cost_excl_water"]),
            "unit": COST_UNIT,
            "region": used,
            "source": source,
        }
    return out


def _water_price(t: Tables, county: str | None, region: str | None) -> float:
    wp = t.water_price
    if county == "Merced" and wp.get("value") is not None:
        return float(wp["value"])
    by_region = wp.get("by_region", {})
    entry = by_region.get(region or DEFAULT_REGION) or by_region.get(DEFAULT_REGION) or {}
    value = entry.get("value", wp.get("value"))
    return float(value) if value is not None else None


def build_context(location: dict, tables: Tables | None = None, crops: list[str] | None = None) -> dict:
    """Context for an already resolved location {state, county, in_california}."""
    t = tables or _default_tables()
    crops = crops or list(reference.crops())
    in_ca = bool(location.get("in_california"))
    county = location.get("county")
    notes: list[str] = []

    region = t.county_region.get(county) if (in_ca and county) else None
    if not in_ca:
        notes.append(OUTSIDE_CA_NOTE)
    elif region is None:
        notes.append(f"{county} County is not in the region table, so costs and water price use {DEFAULT_REGION}.")

    baseline = _baseline_yields(t, county, in_ca, crops, notes)
    costs = _production_costs(t, region, crops, notes)
    water = _water_price(t, county if in_ca else None, region)
    water_region = "Merced Irrigation District" if (in_ca and county == "Merced") else (region or DEFAULT_REGION)
    notes.append(f"Surface water price uses a typical {water_region} value. Actual district rates vary.")

    return {
        "state": location.get("state"),
        "county": county,
        "in_california": in_ca,
        "cost_region": region,
        "baseline_yields": baseline,
        "production_costs": costs,
        "surface_water_price_per_af": water,
        "data_quality": notes,
    }


def get_location_context(lat: float, lon: float) -> dict:
    return build_context(county_lookup.lookup(lat, lon))
