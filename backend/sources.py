"""Farmer-readable sources for every input in the calculation boxes.

A reported value says what the data is, who publishes it, which part was used
(place, years, table, page) and links to the publisher. An estimated value says
what data it was calculated from and by which method, links to both, and lists
the upstream inputs in derived_from. Citations come from the reference files'
own source fields and the records actually used for the run. A source field that
is missing or marked verify=true is flagged as not yet verified, never guessed.
"""
from __future__ import annotations

import csv
import json
import re
from functools import cache
from pathlib import Path
from statistics import median

from backend import reference

ROOT = Path(__file__).resolve().parent.parent
UNVERIFIED = "Source not yet verified"

# Publisher pages. Every link is the publisher's own https page.
LINKS = {
    "nasa": ("NASA POWER", "https://power.larc.nasa.gov"),
    "nass": ("USDA NASS Quick Stats", "https://quickstats.nass.usda.gov"),
    "ucd": ("UC Davis Cost and Return Studies", "https://coststudies.ucdavis.edu"),
    "eia": ("U.S. EIA electricity data", "https://www.eia.gov/electricity/data/browser"),
    "fao56": ("FAO-56 Crop Evapotranspiration", "https://www.fao.org/3/x0490e/x0490e00.htm"),
    "fao66": ("FAO-66 Crop Yield Response to Water (updates FAO-33)", "https://www.fao.org/3/i2800e/i2800e00.htm"),
    "fao25": ("FAO-25 Effective Rainfall", "https://www.fao.org/3/X5560E/X5560E00.htm"),
    "fao_tm4": ("FAO Training Manual No. 4, Irrigation Scheduling", "https://www.fao.org/3/t7202e/t7202e00.htm"),
    "itrc": ("Cal Poly Irrigation Training and Research Center", "https://www.itrc.org"),
    "ucanr": ("UC Agriculture and Natural Resources", "https://ucanr.edu"),
    "sgma": ("California DWR SGMA Portal (well data)", "https://sgma.water.ca.gov/portal/"),
    "apep": ("Advanced Pumping Efficiency Program (pump tests)", "https://jcast.fresnostate.edu/pumpefficiency/pumptesting"),
    "mid": ("Merced Irrigation District", "https://www.mercedid.org"),
    "dwr_ag": ("California DWR Agricultural Water Use Efficiency",
               "https://water.ca.gov/Programs/Water-Use-And-Efficiency/Agricultural-Water-Use-Efficiency"),
}

CROPS = {"almonds": "Almonds", "walnuts": "Walnuts", "processing_tomatoes": "Processing tomatoes",
         "corn": "Corn", "oats": "Oats", "alfalfa_hay": "Alfalfa"}
# The commodity as USDA NASS names it, in plain words.
NASS_NAMES = {"almonds": "almond", "walnuts": "English walnut", "processing_tomatoes": "processing tomato",
              "corn": "corn grain", "oats": "oat", "alfalfa_hay": "alfalfa hay"}
COUNTY_YIELDS = "data/validation/ca_county_yields.csv"
STATE_YIELDS = "data/validation/ca_state_yields.csv"
PRICES = "data/reference/prices/crop_prices.csv"
COST_INDEXES = "data/prices/cost_indexes.csv"
INDEX_NAMES = {"fertilizer": "fertilizer", "chemicals": "agricultural chemicals", "seeds": "seeds and plants",
               "fuels": "fuels", "wages": "farm wage rates", "diesel": "US No 2 diesel retail price",
               "electricity": "California commercial electricity price"}


class Src:
    """One input's source: text, publisher links, upstream inputs, verified flag."""

    def __init__(self, text, links=(), derived_from=(), verified=True):
        self.text, self.links = text, list(links)
        self.derived_from, self.verified = list(derived_from), verified

    def fields(self):
        seen, links = set(), []
        for key in self.links:
            label, url = LINKS[key] if isinstance(key, str) else key
            if url not in seen:
                seen.add(url)
                links.append({"label": label, "url": url})
        return {"source": self.text, "source_url": links[0]["url"] if links else None, "links": links,
                "derived_from": self.derived_from, "source_verified": self.verified}


@cache
def records(path):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@cache
def defaults():
    return json.loads((ROOT / "data/reference/prices/defaults.json").read_text())


def crop_name(crop):
    return CROPS.get(crop, crop.replace("_", " ").capitalize())


def span(years):
    years = sorted(years)
    return f"{years[0]} to {years[-1]}" if years[0] != years[-1] else str(years[0])


def pct(v):
    return f"{v * 100:g}%"


def cite(field_source):
    """'fao56_ch6.pdf, Table 12, p. 11 (Almonds...)' -> 'FAO-56 chapter 6, Table 12, p. 11'."""
    text = field_source.replace("fao56_ch6.pdf", "FAO-56 chapter 6").replace("fao66.pdf", "FAO-66")
    return re.split(r"\s\(|\.\s+(?=[A-Z])|:\s", text, maxsplit=1)[0].strip()


def crop_field(crop, field):
    """(citation or None, verified) for one crops.json field."""
    entry = reference.get_crop(crop).get(field, {})
    src = entry.get("source") if isinstance(entry, dict) else None
    ok = bool(src) and not entry.get("verify")
    return (cite(src) if ok else None), ok


def cited(citation):
    return citation or UNVERIFIED.lower()


def strip_urls(text):
    return re.sub(r"\s*\(https://[^)]*\)", "", text).replace("/af", "/acre-ft").strip()


def urls_in(text):
    return [("District rate sheet", u) for u in re.findall(r"https://[^\s)]+", text)]


# ---------------------------------------------------------------- reported data

def baseline(crop, ctx):
    """USDA NASS median yield behind the baseline, with the county and years used."""
    base = ctx["baseline_yields"][crop]
    county = base["basis"] == "county"
    rows = [r for r in records(COUNTY_YIELDS if county else STATE_YIELDS)
            if r["crop"] == crop and (not county or r.get("county") == ctx.get("county"))]
    where = f"{ctx.get('county')} County" if county else "California statewide"
    if rows and round(median(float(r["yield"]) for r in rows), 3) == base["value"]:
        years = [int(r["year"]) for r in rows]
        text = (f"USDA NASS Quick Stats, {where} {NASS_NAMES.get(crop, crop)} yield, "
                f"{span(years)} median ({len(years)} years)")
        return Src(text, ["nass"], [f"USDA NASS {where} yield, {span(years)}"])
    return Src(f"{UNVERIFIED}: no USDA NASS {where} yield records match this baseline", ["nass"],
               ["USDA NASS yield"], verified=False)


def cost_study(crop, ctx):
    """The cost study behind a crop's cost components (the rows block_cost uses): the UC
    Davis study's region, year and page with its link, or the USDA ERS national average."""
    from backend.simulate import cost_components
    comps = cost_components(crop, ctx) or []
    c = next((x for x in comps if x.basis in ("per_acre", "per_ton")), None)
    if c is None:
        return None
    if c.source.startswith(ERS_LABEL):
        return Src(f"{ERS_LABEL}, {crop_name(crop).lower()}, U.S. total (no California study)",
                   [(ERS_LABEL, c.source_url)], [f"{ERS_LABEL}, {crop_name(crop).lower()}"])
    page = re.search(r"p\.\s?\d+", c.source)
    text = f"UC Davis Cost and Return Study, {crop_name(crop)}, {c.region}, {c.base_year}"
    text += f", {page.group(0)}" if page else ""
    if ctx.get("cost_region") and ctx["cost_region"] != c.region:
        text += f" (used because {ctx['cost_region']} has no {crop_name(crop).lower()} study)"
    return Src(text, [("UC Davis cost study", c.source_url), "ucd"],
               [f"UC Davis cost study, {crop_name(crop)}, {c.region}, {c.base_year}"], bool(page and c.source_url))


def price(crop, p):
    rows = [r for r in records(PRICES) if r["crop"] == crop and int(r["year"]) == p.year]
    if not rows:
        return Src(f"{UNVERIFIED}: no USDA NASS price record for {p.year}", ["nass"],
                   ["USDA NASS price received"], verified=False)
    year_kind = "marketing year" if "MARKETING YEAR" in rows[0]["source"] else "calendar year"
    return Src(f"USDA NASS Quick Stats, California {NASS_NAMES.get(crop, crop)} price received, "
               f"{p.year} {year_kind}", ["nass"], [f"USDA NASS California price received, {p.year}"])


def cost_index(v):
    """A NASS prices-paid index or EIA price (economics.IndexValue) from cost_indexes.csv."""
    rows = [r for r in records(COST_INDEXES) if r["index_name"] == v.name and int(r["year"]) == v.year]
    what = INDEX_NAMES.get(v.name, v.name)
    if not rows:
        return Src(f"{UNVERIFIED}: no {what} record for {v.year}", ["nass"], [f"{what}, {v.year}"], verified=False)
    if rows[0]["source"].startswith("USDA NASS"):
        publisher = "USDA NASS Quick Stats"
        text = f"USDA NASS Prices Paid Index (2011=100), {what}, U.S. annual, {v.year}"
    else:
        publisher = "U.S. EIA"
        text = f"U.S. EIA, {what}, {v.year}"
    if v.is_estimate:
        text += f" (no value for {v.wanted_year}; nearest year used)"
    return Src(text, [(publisher, rows[0]["source_url"])], [f"{publisher} {what}, {v.year}"])


def electricity(e):
    return cost_index(e)


SIMULATION = "YieldGenerator simulation using NASA POWER weather"


def simulation(derived_from=(), verified=True):
    """A simulated quantity (acre-ft applied, harvest tons) for one season."""
    return Src(SIMULATION, ["nasa"], list(derived_from), verified)


def no_harvest_line(crop, c):
    """Why a crop's cost source has no separate per-ton harvest charge."""
    if c is not None and c.source.startswith(ERS_LABEL):
        return Src(f"{ERS_LABEL}, {crop_name(crop).lower()}, U.S. total, {c.base_year}: harvest is inside the "
                   "machinery, fuel, repairs and custom services lines, so there is no separate harvest charge.",
                   [(ERS_LABEL, c.source_url)], [f"{ERS_LABEL}, {crop_name(crop).lower()}"])
    if c is None or not c.source_url:
        return Src(f"{UNVERIFIED}: no cost study row for {crop_name(crop).lower()}", ["ucd"],
                   ["UC Davis cost study"], verified=False)
    page = re.search(r"p\.\s?\d+", c.source)
    return Src(f"UC Davis Cost and Return Study, {crop_name(crop)}, {c.region}, {c.base_year}"
               + (f", {page.group(0)}" if page else "")
               + ": no custom harvest line; the grower's own harvest work is in the machinery and labor costs.",
               [("UC Davis cost study", c.source_url), "ucd"],
               [f"UC Davis cost study, {crop_name(crop)}, {c.region}, {c.base_year}"], bool(page))


ERS_LABEL = "USDA ERS Commodity Costs and Returns"


def cost_component(crop, c):
    """One cost_components.csv row (economics.CostComponent): a UC Davis study line, or a
    USDA ERS national average for a crop with no UC Davis study."""
    if c.source.startswith(ERS_LABEL):
        text = f"{ERS_LABEL}, {crop_name(crop).lower()}, U.S. total, {c.base_year}"
        if c.basis == "per_acre_system":
            text += ": irrigation system. " + c.source.split(": ", 1)[1]
        else:
            text += f", dollars per planted acre: {c.source.split('planted acre: ', 1)[-1]}."
        return Src(text, [(ERS_LABEL, c.source_url)], [f"{ERS_LABEL}, {crop_name(crop).lower()}, {c.base_year}"])
    if not c.source_url:
        return Src(f"{UNVERIFIED}: no UC Davis cost component record for {crop_name(crop).lower()}", ["ucd"],
                   ["UC Davis cost study"], verified=False)
    page = re.search(r"p\.\s?\d+", c.source)
    year = f", {c.base_year}" if c.base_year else ""
    text = f"UC Davis Cost and Return Study, {crop_name(crop)}, {c.region}{year}"
    text += f", {page.group(0)}" if page else ""
    text += f": {c.component.replace('_', ' ')}"
    if c.component == "other" and "includes " in c.source:
        text += f" ({c.source.split('includes ', 1)[1]})"
    return Src(text + ".", [("UC Davis cost study", c.source_url), "ucd"],
               [f"UC Davis cost study, {crop_name(crop)}, {c.region}{year}"], bool(page))


def water_price(ctx):
    """Surface water price: the district rate behind the value, or a flagged default."""
    raw = defaults()["surface_water_price_per_af"]
    value = ctx.get("surface_water_price_per_af")
    src, ok = raw.get("source", ""), not raw.get("verify")
    if ctx.get("county") != "Merced" or raw.get("value") != value:
        entry = raw.get("by_region", {}).get(ctx.get("cost_region") or "San Joaquin Valley North", {})
        if entry.get("value") == value:
            src, ok = entry.get("source", ""), not entry.get("verify")
    if not src:
        return Src(f"{UNVERIFIED}: ${value:g}/acre-ft surface water price", ["dwr_ag"],
                   ["Surface water price default"], verified=False)
    if "Team estimate" in src:
        return Src(f"Default assumption: ${value:g}/acre-ft surface water. {strip_urls(src)} Not measured. "
                   "Replace with your district's rate.", ["dwr_ag"], ["Team estimate, no district rate found"],
                   verified=False)
    links = urls_in(src) + (["mid"] if "Merced Irrigation District" in src else [])
    district = re.split(r"\s\(|:\s|;\s|,\s", strip_urls(src), maxsplit=1)[0]
    return Src(strip_urls(src), links or ["dwr_ag"], [district], ok and bool(src))


# ---------------------------------------------------------------- defaults

def surface_share_default(share):
    return Src(f"Default assumption: {pct(share)} of water from surface water, the rest pumped from wells. "
               "Not measured. Replace with your own value.", ["dwr_ag"], ["Default assumption"])


def well_lift(ft):
    entry = defaults()["well_lift_ft"]
    note = entry.get("source", "")
    text = f"Default assumption: {ft:g} ft well lift. Not measured. Replace with your own value."
    if "DWR SGMA" in note:
        text += " DWR SGMA Portal well data shows depth to water near your farm."
    return Src(text, ["sgma"], ["Team assumption for Merced area well lift" if note else "Default assumption"],
               bool(note) and not entry.get("verify"))


def pump_efficiency(eff):
    entry = defaults()["pump_efficiency"]
    return Src(f"Default assumption: {pct(eff)} pump efficiency (wire to water). Not measured. "
               "Replace with your own value; a pump test measures it.", ["apep"],
               ["Default assumption"], bool(entry.get("source")) and not entry.get("verify"))


# ---------------------------------------------------------------- constants (no links needed)

LB_PER_TON = Src("US short ton: 2,000 lb")
MM_PER_IN = Src("Definition of the inch: 25.4 mm")
MM_PER_FT = Src("Definition of the foot: 304.8 mm")
CENTS = Src("Definition of the cent: 100 cents per dollar")
PERCENT = Src("Fraction x 100 = percent")
KWH = Src("Physics: lifting 1 acre-ft of water 1 ft takes 1.024 kWh at 100% pump efficiency "
          "(1,233.5 cubic meters x 9.81 m/s2 x 0.3048 m / 3.6 million joules per kWh)")


def bushel(crop, lb):
    return Src(f"USDA standard bushel weight for {crop_name(crop).lower()}: {lb:g} lb "
               "(USDA ERS Agricultural Handbook No. 697, 1992)")


# ---------------------------------------------------------------- estimates from weather

def weather(grid, start, end):
    return f"NASA POWER daily weather, grid cell {grid[0]:g}, {grid[1]:g}, {start} to {end}"


def crop_water_use(crop, grid, start, end):
    kc, kc_ok = crop_field(crop, "kc")
    stages, st_ok = crop_field(crop, "stage_days")
    text = (f"Calculated from NASA POWER daily weather (temperature, humidity, wind, sunlight) for grid cell "
            f"{grid[0]:g}, {grid[1]:g}, {start} to {end}, using the FAO-56 Penman-Monteith method and FAO-56 crop "
            f"coefficients for {crop_name(crop).lower()} ({cited(kc)}), with growth stage lengths from {cited(stages)}.")
    return Src(text, ["nasa", "fao56"],
               ["NASA POWER weather", "FAO-56 Penman-Monteith", f"FAO-56 crop coefficients ({cited(kc)})"],
               kc_ok and st_ok)


def soil(texture):
    entry = reference.soils().get(texture, {})
    ok = bool(entry.get("source")) and not entry.get("verify")
    where = cite(entry["source"]) if entry.get("source") else UNVERIFIED.lower()
    return f"{texture} soil holding {entry.get('awc_mm_per_m', 0):g} mm of water per m of roots ({where})", ok


def effective_rain(grid, start, end, texture):
    holds, ok = soil(texture)
    text = (f"Calculated from NASA POWER daily rain for grid cell {grid[0]:g}, {grid[1]:g}, {start} to {end}: rain under "
            f"5 mm in a day is not counted and 80% of larger rain is counted (fixed-percentage method, FAO-25), "
            f"limited by what the root zone can hold ({holds}).")
    return Src(text, ["nasa", "fao25", "fao56"],
               ["NASA POWER daily rain", "FAO-25 effective rainfall rule", "FAO-56 soil water holding (Table 19)"], ok)


def net_irrigation(crop, grid, start, end, texture, capped):
    holds, soil_ok = soil(texture)
    _, kc_ok = crop_field(crop, "kc")
    text = (f"Crop water use minus effective rain (both calculated from NASA POWER weather, grid cell {grid[0]:g}, "
            f"{grid[1]:g}, {start} to {end}), refilling the root zone whenever it dries past half of what the soil "
            f"holds (FAO-56 soil water balance, chapter 8; {holds}).")
    if capped:
        text += " Limited by the farm water cap you entered."
    return Src(text, ["nasa", "fao56"],
               ["Crop water use (FAO-56, NASA POWER)", "Effective rain (NASA POWER, FAO-25)", "FAO-56 soil water balance"],
               soil_ok and kc_ok)


def irrigation_efficiency(method, irr):
    src = irr.get("source", "")
    name = method.replace("_", " ")
    links = (["fao_tm4"] if "Training Manual No. 4" in src else []) + (["itrc", "ucanr"] if "ITRC" in src else [])
    if not src:
        return Src(f"{UNVERIFIED}: {pct(irr['efficiency'])} efficiency for {name} irrigation", links or ["fao_tm4"],
                   ["Irrigation efficiency default"], verified=False)
    text = f"Typical {pct(irr['efficiency'])} application efficiency for {name} irrigation. "
    text += src.replace("Placeholder typical value", "Placeholder value").replace("; check", ", to be checked against") + "."
    derived = "FAO Training Manual No. 4 (Brouwer et al. 1989)" if "Training Manual No. 4" in src else "UC ANR / Cal Poly ITRC guidance"
    return Src(text, links or ["fao_tm4"], [derived + (", to be checked" if irr.get("verify") else "")],
               not irr.get("verify"))


def relative_yield(crop, ky, heat_c, grid, start, end):
    ky_cite, ky_ok = crop_field(crop, "ky")
    heat_cite, heat_ok = crop_field(crop, "heat_stress_c")
    kc_ok = crop_field(crop, "kc")[1] and crop_field(crop, "stage_days")[1]
    text = (f"Calculated from crop water use vs the water the crop actually got (FAO-56 water balance on NASA POWER weather, "
            f"grid cell {grid[0]:g}, {grid[1]:g}, {start} to {end}) using the FAO-33 yield response factor Ky = {ky:g} for "
            f"{crop_name(crop).lower()} ({cited(ky_cite)}), minus a penalty for heat days above this crop's normal, counted "
            f"from NASA POWER daily highs above {heat_c:g} C ({cited(heat_cite)}). The heat penalty (0.25% per extra day, "
            "at most 10%) is a team assumption, not a published value.")
    return Src(text, ["fao66", "fao56", "nasa"],
               ["Crop water use (FAO-56, NASA POWER)", "FAO-33 yield response factor Ky", "NASA POWER daily high temperatures"],
               ky_ok and heat_ok and kc_ok)


def median_relative_yield(crop, years):
    _, ok = crop_field(crop, "ky")
    return Src(f"Median of the {crop_name(crop).lower()} relative yields over {span(years)}, each calculated from NASA "
               "POWER weather with FAO-56 water use and the FAO-33 yield response factor (Ky).",
               ["fao66", "nasa"], [f"Relative yield each year, {span(years)}"], ok)


def heat_days(crop, heat_c, grid, start, end):
    heat_cite, ok = crop_field(crop, "heat_stress_c")
    return Src(f"Counted from NASA POWER daily maximum temperature, grid cell {grid[0]:g}, {grid[1]:g}, {start} to {end}. "
               f"Threshold {heat_c:g} C for {crop_name(crop).lower()} ({cited(heat_cite)}).",
               ["nasa"], ["NASA POWER daily maximum temperature"], ok)


def degree_days(crop, base_c, grid, start, end):
    base_cite, ok = crop_field(crop, "gdd_base_c")
    return Src(f"Calculated from NASA POWER daily high and low temperatures, grid cell {grid[0]:g}, {grid[1]:g}, {start} to "
               f"{end}, above a base of {base_c:g} C for {crop_name(crop).lower()} ({cited(base_cite)}).",
               ["nasa"], ["NASA POWER daily temperatures", "Crop base temperature"], ok)


# ---------------------------------------------------------------- whole-farm yearly values

class Farm:
    """Sources for yearly farm or crop-entry values (harvest, sales, cost, water, yield)."""

    def __init__(self, blocks, price_mode, ctx, grid, years):
        self.blocks, self.price_mode = list(blocks), price_mode
        self.ctx, self.grid, self.years = ctx, grid, list(years)

    def crops(self, scope):
        blocks = self.blocks if scope in (None, "farm") else [b for b in self.blocks if b.id == scope]
        seen = []
        for b in blocks:
            if b.crop not in seen:
                seen.append(b.crop)
        return seen

    @property
    def where(self):
        return f"NASA POWER weather, grid cell {self.grid[0]:g}, {self.grid[1]:g}, {span(self.years)}"

    def baselines(self, scope):
        parts, ok = [], True
        for crop in self.crops(scope):
            if crop in self.ctx.get("baseline_yields", {}):
                s = baseline(crop, self.ctx)
                ok = ok and s.verified
                parts.append(f"{crop_name(crop)}: {s.text}")
        return "; ".join(parts), ok

    def costs(self, scope):
        parts, ok = [], True
        for crop in self.crops(scope):
            s = cost_study(crop, self.ctx)
            if s is not None:
                ok = ok and s.verified
                parts.append(f"{crop_name(crop)}: {s.text}")
        return "; ".join(parts), ok

    def ry_ok(self, scope):
        return all(crop_field(c, "ky")[1] and crop_field(c, "heat_stress_c")[1] for c in self.crops(scope))

    def harvest(self, scope=None):
        bases, ok = self.baselines(scope)
        return Src(f"Calculated each year: USDA NASS median yield ({bases}) scaled by that year's relative yield "
                   f"(FAO-33 Ky on FAO-56 crop water use from {self.where}), times acres.",
                   ["nass", "fao66", "fao56", "nasa"],
                   ["USDA NASS median yield", "Relative yield (FAO-33, FAO-56, NASA POWER)", "Acres (farmer input)"],
                   ok and self.ry_ok(scope))

    def sales(self, scope=None):
        bases, ok = self.baselines(scope)
        mode = {"current": "the latest USDA NASS California price received, applied to every year",
                "historical": "that year's USDA NASS California price received (nearest year when missing)"
                }.get(self.price_mode, "the USDA NASS California price received")
        return Src(f"Calculated each year: harvest (USDA NASS median yield, {bases}, scaled by relative yield from "
                   f"{self.where}) times {mode}.", ["nass", "fao66", "nasa"],
                   ["Harvest (USDA NASS yield, relative yield)", "USDA NASS price received"], ok and self.ry_ok(scope))

    def cost(self, scope=None):
        studies, ok = self.costs(scope)
        water = water_price(self.ctx)
        years = {"current": "the latest year's input prices, applied to every year",
                 "historical": "that year's input prices (nearest year when missing)"}.get(self.price_mode, "")
        return Src(f"Calculated each year as inputs + harvest + water + irrigation system. Inputs, harvest and "
                   f"irrigation system come from the cost studies ({studies}), scaled to {years} by the USDA NASS "
                   f"Prices Paid Index (2011=100) and the U.S. EIA diesel price, times acres (harvest times "
                   f"simulated tons). Water is the acre-ft applied (YieldGenerator simulation using NASA POWER "
                   f"weather, {self.where}) priced at {water.text.rstrip('.')} for surface water and at the U.S. "
                   "EIA California commercial electricity price for well pumping.",
                   ["ucd", "nass", "nasa", "fao56", "eia"] + water.links,
                   ["UC Davis cost studies", "USDA NASS prices-paid indexes", "U.S. EIA diesel price",
                    "Water applied (FAO-56, NASA POWER)", "Surface water price", "U.S. EIA electricity price"],
                   ok and water.verified)

    def margin(self, scope=None):
        s, c = self.sales(scope), self.cost(scope)
        return Src("Sales minus cost for that year. Sales: " + s.text.removeprefix("Calculated each year: ")
                   + " Cost: " + c.text.removeprefix("Calculated each year: "), s.links + c.links,
                   ["Sales (USDA NASS yield and price)", "Cost (UC Davis, water, U.S. EIA)"], s.verified and c.verified)

    def water(self, scope=None):
        from backend.simulate import IRRIGATION_KEYS
        used = {b.irrigation for b in self.blocks if scope in (None, "farm") or b.id == scope}
        table = reference.irrigation()
        ok = all(not table.get(IRRIGATION_KEYS.get(m, m), {}).get("verify", True) for m in used)
        methods = sorted(m.replace("_", " ") for m in used)
        return Src(f"Calculated each year: net irrigation from the FAO-56 soil water balance on {self.where}, "
                   f"divided by the irrigation efficiency for {', '.join(methods)} irrigation, times acres.",
                   ["nasa", "fao56", "fao_tm4"],
                   ["Crop water use (FAO-56, NASA POWER)", "Effective rain (NASA POWER)", "Irrigation efficiency"], ok)

    def relative(self, scope=None):
        return Src(f"Calculated each year: FAO-33 yield response factor (Ky) applied to FAO-56 crop water use vs water "
                   f"received, minus a heat-day penalty (team assumption), from {self.where}; farm value weighted by acres.",
                   ["fao66", "fao56", "nasa"],
                   ["Crop water use (FAO-56, NASA POWER)", "FAO-33 yield response factor Ky", "NASA POWER daily highs"],
                   self.ry_ok(scope))

    def metric(self, metric, scope=None):
        return {"harvest": self.harvest, "sales": self.sales, "revenue": self.sales, "cost": self.cost,
                "margin": self.margin, "profit": self.margin, "water": self.water,
                "yield": self.relative}[metric](scope)
