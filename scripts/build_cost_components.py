"""Split UC Davis operating costs into components that cost indexes can scale.

Reads data/reference/prices/production_costs.csv, opens the study PDF and page each
row cites (data/raw/cost_studies/), and classifies every line item of the
"COSTS AND RETURNS PER ACRE TO PRODUCE" operating-cost section.

Output: data/prices/cost_components.csv with columns
    crop, region, component, basis, amount_usd, base_year, index_name, source, source_url,
    is_estimate, estimate_reason

  base_year              the year printed on the study cover, checked against the PDF.
  is_estimate            true when a region has no conventional study of its own and the
                         rows are copied from a nearby region's study (see BORROWED);
                         estimate_reason says why.

  basis per_acre         operating cost lines, $/acre.
  basis per_ton          harvest_haul, $ per ton of harvest: the study's harvest dollars
                         per acre divided by its yield (study_yield_tons_per_acre, from the
                         Gross Returns line). per_acre rows + per_ton rows x study yield add
                         up to cost_excl_water in production_costs.csv.
  basis excluded         in the study's operating costs but not charged: land rent, which
                         one study (corn, Sacramento Valley & N. SJV 2015) lists there while
                         all others list it in cash overhead. Kept so the sum check holds.
  basis per_acre_system  yearly irrigation system cost, $/acre/yr: installed cost from the
                         study's establishment or investment tables divided by the system
                         life the study gives. Capital cost, not part of the operating sum.
  index_name             the NASS/EIA index in cost_indexes.csv that scales the row, or
                         weighted_inputs for rows with no index of their own ("other" and
                         irrigation systems): the dollar-weighted average ratio of the
                         crop's indexed rows.

Water purchase and pumping lines (the same lines production_costs.csv removes) are
left out: water is costed from simulated acre-feet.

Line items are mapped by their cost group in the study (Fertilizer:, Herbicide:, Labor,
Machinery, ...). Custom lines are split by name: harvest/haul/hull lines go to
harvest_haul, transplants to seed, hand-hoe contract labor to labor. Anything the
study does not break out (interest on operating capital, assessments, pollination,
custom application, ...) goes to "other", and its
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
           "index_name", "study_yield_tons_per_acre", "source", "source_url",
           "is_estimate", "estimate_reason"]
# Rows with no NASS/EIA index of their own ("other", irrigation systems) are scaled by
# the dollar-weighted average ratio of the crop's indexed components.
WEIGHTED_INDEX = "weighted_inputs"
LB_PER_TON = 2000

# Crop and region pairs with no conventional study in the repo, filled from the study
# of a nearby region: (crop, region) -> (region whose production_costs row to copy, reason).
# Statewide and organic studies are never used for a conventional region.
BORROWED = {
    ("alfalfa_hay", "San Joaquin Valley South"): (
        "San Joaquin Valley North",
        "No conventional SJV South alfalfa study available; using the nearest region's study.",
    ),
}

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
                   "harvest_haul", "other", "land_rent"]

# Study PDF on coststudyfiles.ucdavis.edu, found by title, region and year. The
# organic alfalfa PDF could not be located, so it points at the UC Davis organic
# studies listing that carries it.
STUDY_URLS = {
    "alfalfa_sjv_north_sacramento_2020.pdf":
        "https://coststudyfiles.ucdavis.edu/uploads/cs_public/02/ee/02ee0710-8c2c-41ea-8b25-736d1854b737/alfalfasvdraft10420.pdf",
    "alfalfa_statewide_organic_2020.pdf": "https://coststudies.ucdavis.edu/organics",
    "almonds_sacramento_valley_2024.pdf":
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
    "walnuts_sjv_south_2023.pdf":
        "https://coststudyfiles.ucdavis.edu/2024/03/27/23WalnutsSacVal-Final-3.26.24.pdf",
}

# Irrigation systems: (component, page, [(study line, installed $/acre, life years)], note).
# The yearly cost is installed cost / life, summed over the parts. Lives come from the
# same study: its investment table (alfalfa, corn, tomatoes) or its irrigation system
# text (orchards).
IRRIGATION_SYSTEMS = {
    "alfalfa_sjv_north_sacramento_2020.pdf": [
        ("irrigation_system_flood", 15, [('Pipe Main Line 10" 1/2 Mile', 8, 10), ('Syphon Tubes 1.5"', 1, 20)],
         "lives from Table 9 p. 19"),
        ("irrigation_system_sprinkler", 15, [("Sprinkler Pipe", 10, 20), ("Irrigation Pipe Trailer", 3, 10)],
         "lives from Table 9 p. 19"),
    ],
    "alfalfa_statewide_organic_2020.pdf": [
        ("irrigation_system_flood", 15, [("Siphon Tubes", 11, 20)], "life from Table 8 p. 19"),
    ],
    "almonds_sacramento_valley_2024.pdf": [
        ("irrigation_system_micro_sprinkler", 15,
         [("Micro-Sprinkler Irrigation System Installation & Materials", 3500, 50)], "life from p. 12"),
    ],
    "almonds_sjv_south_2024.pdf": [
        ("irrigation_system_drip", 14,
         [("Install Irrigation System: Double Line Drip (materials & labor)", 1800, 23)], "life from p. 12"),
    ],
    "corn_sjv_north_sacramento_2015.pdf": [
        ("irrigation_system_flood", 10, [('Irrigation Main Line 10" 1/4 Mile', 9, 15), ('Siphon Pipe-1.5"', 1, 15)],
         "lives from Table 5 p. 15"),
    ],
    "corn_sjv_south_2015.pdf": [
        ("irrigation_system_flood", 9, [('Irrigation Main Line 10" 1/4 Mile', 22, 15), ('Siphon Pipe-1.5"', 2, 15)],
         "lives from Table 5 p. 14"),
    ],
    "tomatoes_processing_sjv_south_2018.pdf": [
        ("irrigation_system_drip", 13, [("Drip Irrigation System", 750, 25), ("Drip Tape", 300, 3)],
         "lives from Table 5 p. 20"),
    ],
    "walnuts_sacramento_valley_2022.pdf": [
        ("irrigation_system_micro_sprinkler", 14,
         [("Micro-Sprinkler Irrigation System: Materials & Installation", 3600, 30)], "life from p. 11"),
    ],
    "walnuts_sjv_south_2023.pdf": [
        ("irrigation_system_flood", 13, [("Flood Irrigation Setup", 800, 30)],
         "the study gives no life for the flood setup; uses its 30-year Well/Pumps/Filters life (Table 6 p. 21)"),
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
    if group == "land rent":
        return "land_rent"
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


def cover_year(pdf: str) -> int:
    """The study year printed alone on a line of the cover page."""
    with pymupdf.open(STUDY_DIR / pdf) as doc:
        cover = doc[0].get_text("text", sort=True)
    m = re.search(r"^\s*((?:19|20)\d\d)\s*$", cover, re.MULTILINE)
    if not m:
        raise SystemExit(f"{pdf}: no study year on the cover")
    return int(m.group(1))


def study_yield_tons(pdf: str, page: int) -> float:
    """Yield per acre in tons from the first priced line under GROSS RETURNS."""
    with pymupdf.open(STUDY_DIR / pdf) as doc:
        text = doc[page - 1].get_text("text", sort=True)
    section = text.split("OPERATING COSTS")[0]
    m = re.search(r"\s([\d,]+(?:\.\d+)?)\s+(Ton|Lb)\s+[\d,.]+\s+[\d,]+\s*$", section,
                  re.MULTILINE | re.IGNORECASE)
    if not m:
        raise SystemExit(f"{pdf} p{page}: no yield on the Gross Returns line")
    qty = float(m.group(1).replace(",", ""))
    return qty if m.group(2).lower() == "ton" else qty / LB_PER_TON


def build_rows(cost: dict) -> list[dict]:
    pdf, page = re.match(r"(.+\.pdf) p\. (\d+)$", cost["source"]).groups()
    page = int(page)
    year = cover_year(pdf)
    if year != int(cost["study_year"]):
        raise SystemExit(f"{pdf}: cover says {year}, production_costs says {cost['study_year']}")
    lines, total = operating_lines(pdf, page)
    if abs(total - float(cost["cost_per_acre"])) > 0.5:
        raise SystemExit(f"{pdf}: total {total} != production_costs {cost['cost_per_acre']}")

    amounts: dict[str, float] = defaultdict(float)
    members: dict[str, list[str]] = defaultdict(list)
    for component, label, amount in lines:
        amounts[component] += amount
        members[component].append(label)

    tons = study_yield_tons(pdf, page)
    base = {"crop": cost["crop"], "region": cost["region"],
            "base_year": year, "study_yield_tons_per_acre": tons, "source_url": STUDY_URLS[pdf],
            "is_estimate": "false", "estimate_reason": ""}
    study = f"UC Davis cost study {pdf}, Costs and Returns table p. {page}"
    rows = []
    for component in COMPONENT_ORDER:
        if component not in amounts:
            continue
        source = study
        if component == "other":
            source += "; not broken out by the study, includes " + "; ".join(members[component])
        if component == "land_rent":
            rows.append({**base, "component": component, "basis": "excluded",
                         "amount_usd": round(amounts[component], 2), "index_name": "",
                         "source": study + "; " + "; ".join(members[component]) + ". Land rent is listed inside "
                                   "operating costs in this study only; every other study puts it in cash "
                                   "overhead, which the simulated cost leaves out, so it is not charged"})
            continue
        if component == "harvest_haul":
            source += f"; {amounts[component]:g} USD/acre / {tons:g} tons/acre study yield"
            rows.append({**base, "component": component, "basis": "per_ton",
                         "amount_usd": round(amounts[component] / tons, 4),
                         "index_name": INDEX_FOR[component], "source": source})
            continue
        rows.append({**base, "component": component, "basis": "per_acre",
                     "amount_usd": round(amounts[component], 2),
                     "index_name": INDEX_FOR.get(component, WEIGHTED_INDEX), "source": source})
    for component, sys_page, parts, note in IRRIGATION_SYSTEMS.get(pdf, []):
        detail = " + ".join(f"{name} {installed:g} USD / {life} yr" for name, installed, life in parts)
        rows.append({**base, "component": component, "basis": "per_acre_system",
                     "amount_usd": round(sum(installed / life for _, installed, life in parts), 4),
                     "index_name": WEIGHTED_INDEX,
                     "source": f"UC Davis cost study {pdf} p. {sys_page}, installed cost per acre / "
                               f"system life: {detail} ({note})"})

    # The study's whole-dollar lines and subtotals do not always add to its printed
    # total. Book that rounding gap in "other" and say so, so the components match
    # the printed operating cost. A gap above MAX_ROUNDING means a misread or
    # misclassified line, not rounding, and stops the build.
    operating = sum(r["amount_usd"] * (tons if r["basis"] == "per_ton" else 1)
                    for r in rows if r["basis"] in ("per_acre", "per_ton", "excluded"))
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


# ---------------------------------------------------------------- USDA ERS (crops with no UC Davis study)

ERS_FILE = RAW_DIR / "ers" / "oats.csv"
ERS_URL = "https://www.ers.usda.gov/data-products/commodity-costs-and-returns"
ERS_REGION = "U.S. total (ERS)"   # the ERS oats file has no western region
ERS_INDEX = "ers_yearly"          # each year's own ERS value; never index-scaled
ERS_REASON = "National/regional ERS average; no California oats cost study available"
ERS_SYSTEM_REASON = "National ERS average; no California oats cost study."
ERS_SYSTEM_NOTE = ("USDA ERS whole-farm average per planted acre already includes these costs; "
                   "no separate irrigation system line.")
# ERS operating cost item -> component. The file has no irrigation or water item, so water
# is never counted twice. Fuel, lube, and electricity is one ERS line (machinery fuel plus any
# pumping power on irrigated farms) and cannot be split.
ERS_ITEMS = {
    "Seed": "seed",
    "Fertilizer": "fertilizer",
    "Chemicals": "chemicals",
    "Fuel, lube, and electricity": "machinery_fuel",
    "Repairs": "machinery_fuel",
    "Custom services": "other",
    "Other variable expenses": "other",
    "Interest on operating inputs": "other",
}
ERS_TOTAL = "Total, operating costs"


def ers_rows(path=ERS_FILE) -> list[dict]:
    """Oats operating costs per planted acre, U.S. total, one set of rows per year."""
    by_year: dict[int, dict[str, float]] = defaultdict(dict)
    totals: dict[int, float] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["Region"] != "U.S. total" or r["Category"] != "Operating costs":
                continue
            if r["Units"] != "dollars per planted acre":
                raise SystemExit(f"ERS oats: unexpected unit {r['Units']!r}")
            item, year = r["Item"].strip(), int(r["Year"])
            if item == ERS_TOTAL:
                totals[year] = float(r["Value"])
            elif item in ERS_ITEMS:
                by_year[year][item] = float(r["Value"])
            elif re.search(r"irrigat|water", item, re.I):
                continue  # never present today; skipped so water is not counted twice
            else:
                raise SystemExit(f"ERS oats: unmapped operating cost item {item!r}")
    rows = []
    for year in sorted(by_year):
        items = by_year[year]
        amounts: dict[str, float] = defaultdict(float)
        members: dict[str, list[str]] = defaultdict(list)
        for item, value in items.items():
            amounts[ERS_ITEMS[item]] += value
            members[ERS_ITEMS[item]].append(f"{item} {value:g}")
        if abs(sum(items.values()) - totals[year]) > 0.05:
            raise SystemExit(f"ERS oats {year}: items {sum(items.values()):.2f} != total {totals[year]}")
        base = {"crop": "oats", "region": ERS_REGION, "base_year": year, "study_yield_tons_per_acre": "",
                "source_url": ERS_URL, "is_estimate": "true", "estimate_reason": ERS_REASON,
                "index_name": ERS_INDEX, "basis": "per_acre"}
        for component in COMPONENT_ORDER:
            if component in amounts:
                rows.append({**base, "component": component, "amount_usd": round(amounts[component], 2),
                             "source": f"USDA ERS Commodity Costs and Returns, oats, U.S. total, {year}, "
                                       f"dollars per planted acre: {'; '.join(members[component])}"})
        rows.append({**base, "component": "irrigation_system_flood", "basis": "per_acre_system",
                     "amount_usd": 0.0, "estimate_reason": ERS_SYSTEM_REASON,
                     "source": f"USDA ERS Commodity Costs and Returns, oats, U.S. total, {year}: "
                               + ERS_SYSTEM_NOTE})
    print(f"oats                 {ERS_REGION:<32} USDA ERS {min(by_year)}-{max(by_year)}, "
          f"{max(by_year)} operating {totals[max(by_year)]:.2f} USD/acre")
    return rows


def main() -> int:
    with PRODUCTION_COSTS.open(newline="") as f:
        costs = list(csv.DictReader(f))
    rows = []
    for cost in costs:
        rows += build_rows(cost)

    for (crop, region), (from_region, reason) in BORROWED.items():
        if any(c["crop"] == crop and c["region"] == region for c in costs):
            raise SystemExit(f"{crop} / {region} now has its own study; remove it from BORROWED")
        donor = [r for r in rows if r["crop"] == crop and r["region"] == from_region]
        if not donor or any("organic" in r["source"].lower() for r in donor):
            raise SystemExit(f"No conventional {crop} study for {from_region} to borrow")
        rows += [{**r, "region": region, "is_estimate": "true", "estimate_reason": reason,
                  "source": f"{r['source']} (study covers {from_region}, not {region})"} for r in donor]
        print(f"{crop:<20} {region:<32} copied from {from_region} (is_estimate=true)")

    rows += ers_rows()
    write_csv(OUTPUT, COLUMNS, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
