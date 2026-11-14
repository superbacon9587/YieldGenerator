"""Extract per-acre production costs from cost study PDFs (UC Davis style).

Reads every PDF in data/raw/cost_studies/ and writes
data/reference/prices/production_costs.csv with columns:
    crop, study_year, region, cost_per_acre, water_cost_per_acre,
    cost_excl_water, unit, source

  cost_per_acre        "TOTAL OPERATING COSTS/ACRE" from the costs per acre table
  water_cost_per_acre  the "Irrigate" or "Water" line in that same table
  cost_excl_water      cost_per_acre minus water_cost_per_acre
  source               PDF filename plus the page number(s) each value came from

Parsing is heuristic: cost study layouts vary by crop and year. Every value
that cannot be found is left blank and reported as a warning, and the full
table is printed at the end so it can be checked against the PDFs by hand.
For orchard crops the "to produce" (bearing year) table is preferred over
establishment tables.

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
COLUMNS = ["crop", "study_year", "region", "cost_per_acre", "water_cost_per_acre",
           "cost_excl_water", "unit", "source"]

CROP_PATTERNS = {
    "almonds": r"\balmonds?\b",
    "walnuts": r"\bwalnuts?\b",
    "processing_tomatoes": r"\bprocessing\s+tomato(es)?\b",
    "corn": r"\b(silage\s+)?corn\b",
    "oats": r"\boats?\b",
    "alfalfa_hay": r"\balfalfa\b",
}

REGION_PATTERN = re.compile(
    r"\b((?:NORTHERN|SOUTHERN|NORTH|SOUTH|CENTRAL)?\s*(?:SAN JOAQUIN|SACRAMENTO)\s+VALLEY"
    r"(?:\s*[-,]?\s*(?:NORTH|SOUTH|CENTRAL|NORTHERN|SOUTHERN))?|INTERMOUNTAIN REGION|"
    r"IMPERIAL COUNTY|[A-Z]+ COUNTY)\b",
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
NUMBER = r"\(?-?[\d,]+(?:\.\d+)?\)?"
TOTAL_OPERATING = re.compile(r"TOTAL\s+OPERATING\s+COSTS?\s*/\s*ACRE", re.IGNORECASE)
WATER_LINE = re.compile(r"^\s*(Irrigat\w*|Water)\b(?!\s*(system|pump|well|sys))", re.IGNORECASE)
PRODUCE_TABLE = re.compile(r"COSTS\s+PER\s+ACRE\s+TO\s+PRODUCE", re.IGNORECASE)
ANY_COSTS_TABLE = re.compile(r"COSTS\s+PER\s+ACRE", re.IGNORECASE)


def to_number(token: str) -> float:
    neg = token.startswith("(") and token.endswith(")")
    value = float(token.strip("()").replace(",", ""))
    return -value if neg else value


def last_number(line: str) -> float | None:
    """Cost tables put the per acre total in the right-most column."""
    tokens = re.findall(NUMBER, line)
    tokens = [t for t in tokens if re.search(r"\d", t)]
    return to_number(tokens[-1]) if tokens else None


def detect_crop(filename: str, first_page: str) -> str | None:
    for text in (filename.replace("_", " ").replace("-", " "), first_page):
        for crop, pattern in CROP_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return crop
    return None


def detect_year(first_page: str) -> int | None:
    years = [int(y) for y in YEAR_PATTERN.findall(first_page)]
    return max(years) if years else None


def detect_region(first_page: str) -> str | None:
    m = REGION_PATTERN.search(first_page)
    return " ".join(m.group(1).split()).title() if m else None


def find_cost_table_pages(pages: list[str]) -> list[int]:
    """Indexes of pages that hold a costs per acre table, "to produce" tables first."""
    produce = [i for i, t in enumerate(pages) if PRODUCE_TABLE.search(t) and TOTAL_OPERATING.search(t)]
    other = [i for i, t in enumerate(pages)
             if i not in produce and ANY_COSTS_TABLE.search(t) and TOTAL_OPERATING.search(t)]
    return produce + other


def extract_from_page(text: str) -> tuple[float | None, float | None]:
    total = water = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if water is None and WATER_LINE.search(line):
            water = last_number(line)
        if total is None and TOTAL_OPERATING.search(line):
            total = last_number(line)
            # Some layouts put the numbers on the following line.
            if total is None and i + 1 < len(lines):
                total = last_number(lines[i + 1])
    return total, water


def extract_pdf(path: Path) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    with pymupdf.open(path) as doc:
        pages = [page.get_text("text", sort=True) for page in doc]
    first = "\n".join(pages[:2])

    row = {c: "" for c in COLUMNS}
    row["unit"] = "$/acre"
    row["crop"] = detect_crop(path.name, first) or ""
    row["study_year"] = detect_year(pages[0] if pages else "") or ""
    row["region"] = detect_region(first) or ""

    # Take both values from the first cost table page that has a total, so the
    # water line and the total always come from the same table.
    total_page = water_page = None
    for idx in find_cost_table_pages(pages):
        total, water = extract_from_page(pages[idx])
        if total is None:
            continue
        row["cost_per_acre"], total_page = total, idx + 1
        if water is not None:
            row["water_cost_per_acre"], water_page = water, idx + 1
        break

    if row["cost_per_acre"] != "" and row["water_cost_per_acre"] != "":
        row["cost_excl_water"] = round(row["cost_per_acre"] - row["water_cost_per_acre"], 2)

    pages_used = sorted({p for p in (total_page, water_page) if p})
    page_str = ", ".join(f"p. {p}" for p in pages_used) if pages_used else "page not found"
    row["source"] = f"{path.name} {page_str}"

    for field in ("crop", "study_year", "region", "cost_per_acre", "water_cost_per_acre"):
        if row[field] == "":
            warnings.append(f"{path.name}: could not find {field}")
    return row, warnings


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
        row, warns = extract_pdf(pdf)
        rows.append(row)
        warnings.extend(warns)

    rows.sort(key=lambda r: (r["crop"], str(r["study_year"])))
    if args.out.resolve().is_relative_to(PROJECT_ROOT):
        write_csv(args.out, COLUMNS, rows)
    print()
    print_table(rows)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
