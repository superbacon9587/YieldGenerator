"""Extract per-acre production costs from UC Davis cost study PDFs.

Reads every PDF in data/raw/cost_studies/ and writes
data/reference/prices/production_costs.csv with columns:
    crop, region, study_year, cost_per_acre, water_cost_per_acre,
    cost_excl_water, unit, source

  cost_per_acre        "TOTAL OPERATING COSTS/ACRE" from the study's
                       "COSTS AND RETURNS PER ACRE TO PRODUCE" table
  water_cost_per_acre  the water purchase and pumping line(s) under "Irrigation:" in
                       that same table (acre-inches applied times $/acre-inch). Irrigation
                       labor and system upkeep stay in cost_excl_water, because the
                       engine prices only the water itself (surface water $/af and
                       groundwater pumping energy).
  cost_excl_water      cost_per_acre minus water_cost_per_acre
  region               one of the cost regions in data/reference/ca_regions.json. A study
                       that covers two regions (for example "Sacramento Valley and
                       Northern San Joaquin Valley") gets one row per region. A statewide
                       study gets "California statewide", and an organic study has
                       "(organic)" appended, so neither is picked up as a regional
                       conventional cost.
  study_year           the year printed on the study cover (not the filename, which can
                       be wrong)
  source               PDF filename plus the page the values came from

Total and water always come from the same page. Values that cannot be found are left
blank and reported as warnings, and the full table is printed so it can be checked
against the PDFs by hand.

Usage:
    python scripts/extract_production_costs.py [--dir data/raw/cost_studies]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pymupdf

from _common import PRICES_DIR, PROJECT_ROOT, RAW_DIR, write_csv

OUTPUT = PRICES_DIR / "production_costs.csv"
COLUMNS = ["crop", "region", "study_year", "cost_per_acre", "water_cost_per_acre",
           "cost_excl_water", "unit", "source"]
STATEWIDE = "California statewide"

# Matched against the cover page. Order matters: processing tomatoes before any
# generic pattern, and alfalfa before corn (some alfalfa studies mention corn).
CROP_PATTERNS = {
    "processing_tomatoes": r"\bprocess(ing)?\s+tomato(es)?\b",
    "almonds": r"\balmonds?\b",
    "walnuts": r"\bwalnuts?\b",
    "alfalfa_hay": r"\balfalfa\b",
    "corn": r"\b(field|grain|silage)?\s*corn\b",
    "oats": r"\boats?\b",
}

# Cover page phrase -> cost region. Checked in order; a cover that names both valleys
# yields both regions.
REGION_PATTERNS = [
    (r"(southern\s+san\s+joaquin|san\s+joaquin\s+valley\s*[-,]?\s*south)", "San Joaquin Valley South"),
    (r"(northern\s+san\s+joaquin|san\s+joaquin\s+valley\s*[-,]?\s*north)", "San Joaquin Valley North"),
    (r"sacramento\s+valley", "Sacramento Valley"),
    (r"central\s+coast|monterey|santa\s+barbara|san\s+luis\s+obispo", "Central Coast"),
    (r"imperial|riverside|ventura|san\s+diego|southern\s+california", "Southern California"),
    (r"intermountain|siskiyou|modoc|lassen", "Mountain"),
    (r"north\s+coast|sonoma|mendocino|napa", "North Coast"),
]

YEAR_LINE = re.compile(r"^\s*((?:19|20)\d\d)\s*$", re.MULTILINE)
COSTS_AND_RETURNS = re.compile(r"COSTS\s+AND\s+RETURNS\s+PER\s+ACRE\s+TO\s+PRODUCE", re.IGNORECASE)
TOTAL_OPERATING = re.compile(r"TOTAL\s+OPERATING\s+COSTS?\s*/\s*ACRE", re.IGNORECASE)
GROUP_HEADER = re.compile(r"^\s*[A-Za-z][A-Za-z /&]*:\s+[\d,]+\s*$")
WATER_LINE = re.compile(r"^\s*Water\b.*\b(AcIn|Ac\s*In|AcFt|acin)\b", re.IGNORECASE)
NUMBER = re.compile(r"-?[\d,]*\d(?:\.\d+)?")


def last_number(line: str) -> float | None:
    tokens = NUMBER.findall(line)
    return float(tokens[-1].replace(",", "")) if tokens else None


def detect_crop(cover: str) -> str | None:
    for crop, pattern in CROP_PATTERNS.items():
        if re.search(pattern, cover, re.IGNORECASE):
            return crop
    return None


def detect_year(cover: str) -> int | None:
    """The study year sits alone on a line near the top of the cover."""
    m = YEAR_LINE.search(cover)
    return int(m.group(1)) if m else None


def detect_regions(cover: str) -> list[str]:
    regions = [name for pattern, name in REGION_PATTERNS if re.search(pattern, cover, re.IGNORECASE)]
    if not regions and re.search(r"^\s*CALIFORNIA\s*$", cover, re.MULTILINE):
        regions = [STATEWIDE]
    if re.search(r"\borganic\b", cover, re.IGNORECASE):
        regions = [f"{r} (organic)" for r in regions]
    return regions


def extract_costs(pages: list[str]) -> tuple[float | None, float | None, int | None]:
    """(total operating $/acre, water $/acre, 1-based page) from the costs and returns table."""
    for idx, text in enumerate(pages):
        if not (COSTS_AND_RETURNS.search(text) and TOTAL_OPERATING.search(text)):
            continue
        total = water = None
        in_irrigation = False
        for line in text.splitlines():
            if GROUP_HEADER.match(line):
                in_irrigation = line.strip().lower().startswith("irrigation")
                continue
            if in_irrigation and WATER_LINE.match(line):
                water = (water or 0.0) + (last_number(line) or 0.0)
            if total is None and TOTAL_OPERATING.search(line):
                total = last_number(line)
        if total is not None:
            return total, water, idx + 1
    return None, None, None


def extract_pdf(path: Path) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    with pymupdf.open(path) as doc:
        pages = [page.get_text("text", sort=True) for page in doc]
    cover = pages[0] if pages else ""

    crop = detect_crop(cover)
    year = detect_year(cover)
    regions = detect_regions(cover)
    total, water, page = extract_costs(pages)

    for name, value in (("crop", crop), ("study_year", year), ("region", regions),
                        ("cost_per_acre", total), ("water_cost_per_acre", water)):
        if not value:
            warnings.append(f"{path.name}: could not find {name}")

    base = {
        "crop": crop or "",
        "study_year": year or "",
        "cost_per_acre": total if total is not None else "",
        "water_cost_per_acre": water if water is not None else "",
        "cost_excl_water": round(total - water, 2) if total is not None and water is not None else "",
        "unit": "$/acre",
        "source": f"{path.name} p. {page}" if page else f"{path.name} page not found",
    }
    return [{**base, "region": r} for r in (regions or [""])], warnings


def print_table(rows: list[dict]) -> None:
    if not rows:
        return
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in COLUMNS}
    print("  ".join(c.ljust(widths[c]) for c in COLUMNS))
    print("  ".join("-" * widths[c] for c in COLUMNS))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in COLUMNS))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=RAW_DIR / "cost_studies")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    pdfs = sorted(p for p in args.dir.glob("*") if p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDFs found in {args.dir}. Nothing written.", file=sys.stderr)
        return 1

    rows, warnings = [], []
    for pdf in pdfs:
        new_rows, warns = extract_pdf(pdf)
        rows.extend(new_rows)
        warnings.extend(warns)

    # Regional conventional studies before statewide or organic ones, so code that
    # takes "the first row" for a crop gets a conventional cost.
    rows.sort(key=lambda r: (r["crop"], "(organic)" in r["region"] or r["region"] == STATEWIDE,
                             r["region"], str(r["study_year"])))
    write_csv(args.out, COLUMNS, rows) if args.out.resolve().is_relative_to(PROJECT_ROOT) else None
    print()
    print_table(rows)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
