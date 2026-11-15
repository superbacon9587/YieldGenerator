"""Split UC Davis operating costs into components that cost indexes can scale.

Reads data/reference/prices/production_costs.csv, opens the study PDF and page each
row cites (data/raw/cost_studies/), and classifies every line item of the
"COSTS AND RETURNS PER ACRE TO PRODUCE" operating-cost section.

Output: data/prices/cost_components.csv with columns
    crop, region, component, basis, amount_usd, base_year, index_name, source, source_url

  basis per_acre         operating cost lines, $/acre. For every crop and region these
                         add up to cost_excl_water in production_costs.csv. Harvest lines
                         priced per ton or per lb in the study are stored per acre at the
                         study yield, so the sum check holds.
  basis per_acre_system  installed cost of the irrigation system, $/acre, from the study's
                         establishment or investment tables. Capital cost, not operating,
                         so it is not part of the operating sum.

Water purchase and pumping lines (the same lines production_costs.csv removes) are
left out: water is costed from simulated acre-feet.

Line items are mapped by their cost group in the study (Fertilizer:, Herbicide:, Labor,
Machinery, ...). Custom lines are split by name: harvest/haul/hull lines go to
harvest_haul, transplants to seed, hand-hoe contract labor to labor. Anything the
study does not break out (interest on operating capital, assessments, pollination,
custom application, land rent inside operating costs, ...) goes to "other", and its
source column lists the study lines it contains. The study rounds each line to whole
dollars, so lines can miss its printed total by a dollar or two. That gap is booked in
"other" with the amount noted, and anything above $3 stops the build.

Usage:
    python scripts/build_cost_components.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict

import pymupdf

from _common import PRICES_DIR, PROJECT_ROOT, RAW_DIR, write_csv

PRODUCTION_COSTS = PRICES_DIR / "production_costs.csv"
OUTPUT = PROJECT_ROOT / "data" / "prices" / "cost_components.csv"
STUDY_DIR = RAW_DIR / "cost_studies"
COLUMNS = ["crop", "region", "component", "basis", "amount_usd", "base_year",
           "index_name", "source", "source_url"]

INDEX_FOR = {
    "seed": "seeds",
    "fertilizer": "fertilizer",
    "chemicals": "chemicals",
    "labor": "wages",
    "machinery_fuel": "diesel",
    "harvest_haul": "diesel",
}
MAX_ROUNDING = 3  # dollars per crop and region
COMPONENT_ORDER = ["seed", "fertilizer", "chemicals", "labor", "machinery_fuel",
                   "harvest_haul", "other"]

# Study PDF on coststudyfiles.ucdavis.edu, found by title, region and year. The
# organic alfalfa PDF could not be located, so it points at the UC Davis organic
# studies listing that carries it.
STUDY_URLS = {
    "alfalfa_sjv_north_sacramento_2020.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/cs_public/02/ee/02ee0710-8c2c-41ea-8b25-736d1854b737/alfalfasvdraft10420.pdf",
    "alfalfa_sjv_south_2016.pdf": "https://coststudies.ucdavis.edu/organics",
    "almonds_sacramento_valley_2022.pdf":
        "https://coststudyfiles.ucdavis.edu/2024/07/09/2024SacValleyAlmonds7.5.24.%20Final%20draft.pdf",
    "almonds_sjv_south_2024.pdf":
        "https://coststudyfiles.ucdavis.edu/2025/08/11/2024%20AlmondsSJVsouth.Final%20Draft.8.3.25.pdf",
    "corn_sjv_north_sacramento_2015.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/cs_public/03/dc/03dc4496-32af-47c6-b479-38e1d27c134e/15cornsacramentovalleyfinaldraftjuly20.pdf",
    "corn_sjv_south_2015.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/cs_public/8a/b9/8ab9b6ef-72ca-4762-af3c-50b487da72c5/corn-sjv-2015.pdf",
    "tomatoes_processing_sjv_south_2018.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/cs_public/2e/7a/2e7a8cf0-b7fd-4207-b945-7b4b8a82625c/17processtomatofresnosdi-final_draft.pdf",
    "walnuts_sacramento_valley_2022.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/pub/2023/03/17/22walnutssacval-31623.pdf",
    "walnuts_sjv_south_2023.pdf.pdf":
        "https://coststudyfiles.ucdavis.edu/2024/03/27/23WalnutsSacVal-Final-3.26.24.pdf",
}

# Irrigation system installed cost, $/acre: (component, amount, page, study lines).
IRRIGATION_SYSTEMS = {
    "alfalfa_sjv_north_sacramento_2020.pdf": [
        ("irrigation_system_flood", 9, 15, 'Pipe Main Line 10" 1/2 Mile 8 + Syphon Tubes 1'),
        ("irrigation_system_sprinkler", 13, 15, "Sprinkler Pipe 10 + Irrigation Pipe Trailer 3"),
    ],
    "alfalfa_sjv_south_2016.pdf": [
        ("irrigation_system_flood", 11, 15, "Siphon Tubes 11"),
    ],
    "almonds_sacramento_valley_2022.pdf": [
        ("irrigation_system_sprinkler", 3500, 15, "Micro-Sprinkler Irrigation System Installation & Materials"),
    ],
    "almonds_sjv_south_2024.pdf": [
        ("irrigation_system_drip", 1800, 14, "Install Irrigation System: Double Line Drip (materials & labor)"),
    ],
    "corn_sjv_north_sacramento_2015.pdf": [
        ("irrigation_system_flood", 10, 10, 'Irrigation Main Line 10" 1/4 Mile 9 + Siphon Pipe-1.5" 1'),
    ],
    "corn_sjv_south_2015.pdf": [
        ("irrigation_system_flood", 24, 9, 'Irrigation Main Line 10" 1/4 Mile 22 + Siphon Pipe-1.5" 2'),
    ],
    "tomatoes_processing_sjv_south_2018.pdf": [
        ("irrigation_system_drip", 1050, 13, "Drip Irrigation System 750 + Drip Tape 300"),
    ],
    "walnuts_sacramento_valley_2022.pdf": [
        ("irrigation_system_sprinkler", 3600, 14, "Micro-Sprinkler Irrigation System: Materials & Installation"),
    ],
    "walnuts_sjv_south_2023.pdf.pdf": [
        ("irrigation_system_flood", 800, 13, "Flood Irrigation Setup"),
    ],
}

CHEMICAL_GROUPS = {"herbicide", "insecticide", "insecticid", "fungicide", "rodenticide",
                   "bactericide", "tree aids", "growth regulator", "vertebrate pest control"}
GROUP_HEADER = re.compile(r"^([A-Za-z][A-Za-z /&]*?)(:)?\s+[\d,]+$")
WATER_LINE = re.compile(r"^\s*Water\b.*\b(AcIn|Ac\s*In|AcFt|acin)\b", re.IGNORECASE)
HARVEST_LINE = re.compile(r"harvest|haul|hull/shell|shake sweep pickup", re.IGNORECASE)
NUMBER = re.compile(r"-?[\d,]*\d(?:\.\d+)?")


def last_number(line: str) -> float:
    return float(NUMBER.findall(line)[-1].replace(",", ""))


def item_name(line: str) -> str:
    """Line text up to the first quantity column (the PDF separates columns by 2+ spaces)."""
    return re.split(r"\s{2,}", line.strip())[0]


def classify(group: str, line: str) -> str | None:
    """Component for one operating line, or None for water (excluded)."""
    name = item_name(line)
    if group == "irrigation":
        if WATER_LINE.match(line):
            return None
        return "chemicals" if re.search(r"phuric", name, re.I) else "other"
    if group == "fertilizer":
        return "fertilizer"
    if group in CHEMICAL_GROUPS:
        return "chemicals"
    if group == "seed":
        return "seed"
    if group == "labor":
        return "labor"
    if group == "machinery":
        return "machinery_fuel"
    if group == "contract" and re.search(r"hand hoe", name, re.I):
        return "labor"
    if group == "custom":
        if re.search(r"transplant", name, re.I):
            return "seed"
        if HARVEST_LINE.search(name) and not re.search(r"analysis", name, re.I):
            return "harvest_haul"
    return "other"


def operating_lines(pdf: str, page: int) -> tuple[list[tuple[str, str, float]], float]:
    """[(component, study line, $/acre)] and the study's total operating $/acre.

    The study rounds every line and every group subtotal to whole dollars. A group
    whose lines all land in one component is taken at its subtotal, which keeps
    rounding error to one dollar per group. Line items are used only where a group
    is split across components.
    """
    with pymupdf.open(STUDY_DIR / pdf) as doc:
        text = doc[page - 1].get_text("text", sort=True)
    raw = [ln.strip() for ln in text.splitlines()]
    start = next(i for i, ln in enumerate(raw) if ln == "OPERATING COSTS")

    groups: list[dict] = []  # {"name", "subtotal", "lines": [(component, label, amount)]}
    extra: list[tuple[str, str, float]] = []
    for ln in raw[start + 1:]:
        flat = re.sub(r"\s+", " ", ln)
        if re.match(r"TOTAL OPERATING COSTS ?/ ?ACRE", flat):
            break
        if not flat:
            continue
        if flat.startswith("Interest on Operating Capital"):
            extra.append(("other", "Interest on operating capital", last_number(flat)))
            continue
        header = GROUP_HEADER.match(flat)
        if header and (header.group(2) or header.group(1).lower() in {"labor", "machinery"}):
            name = header.group(1).strip().lower()
            groups.append({"name": name, "subtotal": last_number(flat), "lines": []})
            continue
        if not groups:
            raise SystemExit(f"{pdf} p{page}: line before any cost group: {flat!r}")
        group = groups[-1]
        group["lines"].append((classify(group["name"], ln), f"{group['name'].title()}: {item_name(ln)}",
                               last_number(flat)))
    else:
        raise SystemExit(f"{pdf} p{page}: TOTAL OPERATING COSTS/ACRE not found")

    out = []
    for group in groups:
        line_sum = sum(amount for _, _, amount in group["lines"])
        if abs(line_sum - group["subtotal"]) > len(group["lines"]):
            raise SystemExit(f"{pdf} p{page}: {group['name']} lines add to {line_sum}, "
                             f"subtotal is {group['subtotal']}")
        components = {c for c, _, _ in group["lines"]}
        if len(components) == 1 and None not in components:
            labels = [label for _, label, _ in group["lines"]]
            out.append((components.pop(), "; ".join(labels), group["subtotal"]))
        else:
            out += [line for line in group["lines"] if line[0] is not None]
    return out + extra, last_number(re.sub(r"\s+", " ", ln))


def build_rows(cost: dict) -> list[dict]:
    pdf, page = re.match(r"(.+\.pdf) p\. (\d+)$", cost["source"]).groups()
    page = int(page)
    lines, total = operating_lines(pdf, page)
    if abs(total - float(cost["cost_per_acre"])) > 0.5:
        raise SystemExit(f"{pdf}: total {total} != production_costs {cost['cost_per_acre']}")

    amounts: dict[str, float] = defaultdict(float)
    members: dict[str, list[str]] = defaultdict(list)
    for component, label, amount in lines:
        amounts[component] += amount
        members[component].append(label)

    base = {"crop": cost["crop"], "region": cost["region"],
            "base_year": int(cost["study_year"]), "source_url": STUDY_URLS[pdf]}
    study = f"UC Davis cost study {pdf}, Costs and Returns table p. {page}"
    rows = []
    for component in COMPONENT_ORDER:
        if component not in amounts:
            continue
        source = study
        if component == "other":
            source += "; not broken out by the study, includes " + "; ".join(members[component])
        rows.append({**base, "component": component, "basis": "per_acre",
                     "amount_usd": round(amounts[component], 2),
                     "index_name": INDEX_FOR.get(component, ""), "source": source})
    for component, amount, sys_page, detail in IRRIGATION_SYSTEMS.get(pdf, []):
        rows.append({**base, "component": component, "basis": "per_acre_system",
                     "amount_usd": amount, "index_name": "",
                     "source": f"UC Davis cost study {pdf} p. {sys_page}, installed cost per acre: {detail}"})

    # The study's whole-dollar lines and subtotals do not always add to its printed
    # total. Book that rounding gap in "other" and say so, so the components match
    # the printed operating cost. A gap above MAX_ROUNDING means a misread or
    # misclassified line, not rounding, and stops the build.
    operating = sum(r["amount_usd"] for r in rows if r["basis"] == "per_acre")
    gap = round(float(cost["cost_excl_water"]) - operating, 2)
    if abs(gap) > MAX_ROUNDING:
        raise SystemExit(f"{pdf}: components {operating} vs cost_excl_water {cost['cost_excl_water']}")
    if gap:
        other = next(r for r in rows if r["component"] == "other")
        other["amount_usd"] = round(other["amount_usd"] + gap, 2)
        other["source"] += (f"; {gap:+.0f} USD rounding adjustment so components match the study's "
                            f"printed total operating cost")
    print(f"{cost['crop']:<20} {cost['region']:<32} excl. water {float(cost['cost_excl_water']):>7.0f}  "
          f"rounding gap {gap:+.0f}")
    return rows


def main() -> int:
    with PRODUCTION_COSTS.open(newline="") as f:
        costs = list(csv.DictReader(f))
    rows = []
    for cost in costs:
        rows += build_rows(cost)
    write_csv(OUTPUT, COLUMNS, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
