"""Profit and loss calculations for YieldGenerator.

Main entry points:
    block_cost()           the cost of one crop block in one year; every cost in the app
                           (simulate, summary, compare, comparisons, optimize) comes from it
    year_used()            which year's prices and cost indexes a simulated year uses
    pumping_cost_per_af()  groundwater pumping cost in $ per acre-ft

Unit handling is explicit. Prices carry the unit string they were published with
(NASS "$ / LB", "$ / TON", "$ / BU", "$ / CWT"; EIA "cents per kilowatt-hour"),
and yields carry their own unit, so a yield in tons per acre can be valued at a
price in $ per pound. Bushel conversions are crop specific (see BUSHEL_LB).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from backend.rounding import rnd

PRICES_DIR = Path(__file__).resolve().parent.parent / "data" / "reference" / "prices"
COST_DIR = Path(__file__).resolve().parent.parent / "data" / "prices"

# Energy to lift 1 acre-ft of water 1 ft at 100% efficiency, in kWh
# (1 acre-ft = 1,233.5 m3; 1,233.5 m3 x 1,000 kg x 9.81 m/s2 x 0.3048 m / 3.6e6 J/kWh).
KWH_PER_AF_FT = 1.024

PRICE_MODES = ("current", "historical")

# Mass units expressed in pounds.
LB_PER_UNIT = {"LB": 1.0, "CWT": 100.0, "TON": 2000.0}

# Standard USDA test weights, pounds per bushel.
BUSHEL_LB = {"corn": 56.0, "oats": 32.0}

# Electricity units expressed in $ per kWh.
DOLLARS_PER_KWH = {"$/KWH": 1.0, "CENTS/KWH": 0.01}


class PriceNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------- units

def normalize_unit(unit: str) -> str:
    """Reduce a unit string to a bare quantity unit.

    "$ / LB" -> "LB", "tons/acre" -> "TON", "cents per kilowatt-hour" -> "CENTS/KWH".
    """
    u = unit.strip().upper()
    u = re.sub(r"\s+PER\s+", "/", u)
    u = u.replace(" ", "")
    u = u.replace("KILOWATT-HOUR", "KWH").replace("KILOWATTHOUR", "KWH")
    if u in DOLLARS_PER_KWH:
        return u
    u = u.removeprefix("$/")
    u = u.removesuffix("/ACRE").removesuffix("/AC")
    aliases = {
        "LBS": "LB", "POUND": "LB", "POUNDS": "LB",
        "TONS": "TON", "SHORTTON": "TON", "SHORTTONS": "TON",
        "BUSHEL": "BU", "BUSHELS": "BU",
        "HUNDREDWEIGHT": "CWT",
    }
    return aliases.get(u, u)


def unit_to_lb(unit: str, crop: str | None = None) -> float:
    """Pounds in one of `unit`. Bushels need the crop to pick a test weight."""
    u = normalize_unit(unit)
    if u in LB_PER_UNIT:
        return LB_PER_UNIT[u]
    if u == "BU":
        if crop not in BUSHEL_LB:
            raise ValueError(f"No bushel weight defined for crop {crop!r}")
        return BUSHEL_LB[crop]
    raise ValueError(f"Unsupported quantity unit: {unit!r}")


def convert_quantity(amount: float, from_unit: str, to_unit: str, crop: str | None = None) -> float:
    if normalize_unit(from_unit) == normalize_unit(to_unit):
        return amount
    return amount * unit_to_lb(from_unit, crop) / unit_to_lb(to_unit, crop)


def electricity_to_dollars_per_kwh(price: float, unit: str) -> float:
    u = normalize_unit(unit)
    if u not in DOLLARS_PER_KWH:
        raise ValueError(f"Unsupported electricity unit: {unit!r}")
    return price * DOLLARS_PER_KWH[u]


# ---------------------------------------------------------------- pumping

def pumping_kwh_per_af(lift_ft: float, efficiency: float) -> float:
    if not 0 < efficiency <= 1:
        raise ValueError(f"Pump efficiency must be in (0, 1], got {efficiency}")
    if lift_ft < 0:
        raise ValueError(f"Lift must be non-negative, got {lift_ft}")
    return lift_ft * KWH_PER_AF_FT / efficiency


def pumping_cost_per_af(lift_ft: float, efficiency: float, electricity_price: float,
                        electricity_unit: str = "$/kWh") -> float:
    """Cost to pump one acre-ft: 1 af x lift_ft x 1.02 kWh/(af ft) / efficiency x $/kWh."""
    return pumping_kwh_per_af(lift_ft, efficiency) * electricity_to_dollars_per_kwh(
        electricity_price, electricity_unit)


# ---------------------------------------------------------------- price tables

@dataclass(frozen=True)
class Price:
    value: float
    unit: str
    year: int  # the year the price actually comes from


class PriceTable:
    """Annual prices keyed by series name (crop or utility type) and year."""

    def __init__(self, rows: list[dict], key_column: str):
        self._data: dict[str, dict[int, Price]] = {}
        for r in rows:
            year = int(r["year"])
            self._data.setdefault(r[key_column], {})[year] = Price(float(r["price"]), r["unit"], year)

    @classmethod
    def from_csv(cls, path: Path, key_column: str) -> "PriceTable":
        with Path(path).open(newline="") as f:
            return cls(list(csv.DictReader(f)), key_column)

    def get(self, key: str, year: int, price_mode: str = "current") -> Price:
        if price_mode not in PRICE_MODES:
            raise ValueError(f"price_mode must be one of {PRICE_MODES}, got {price_mode!r}")
        series = self._data.get(key)
        if not series:
            raise PriceNotFoundError(f"No prices for {key!r}")
        if price_mode == "current":
            return series[max(series)]
        if year not in series:
            raise PriceNotFoundError(f"No {key!r} price for {year} (available: {min(series)}-{max(series)})")
        return series[year]


def load_crop_prices(path: Path = PRICES_DIR / "crop_prices.csv") -> PriceTable:
    return PriceTable.from_csv(path, "crop")


def load_defaults(path: Path = PRICES_DIR / "defaults.json") -> dict:
    """Return {name: value}. Unfilled placeholders come back as None."""
    raw = json.loads(Path(path).read_text())
    return {name: entry["value"] for name, entry in raw.items()}




# ---------------------------------------------------------------- cost indexes

WEIGHTED_INDEX = "weighted_inputs"  # rows with no index of their own (see block_cost)
ERS_YEARLY = "ers_yearly"           # USDA ERS rows: one set per year, used as is (no index scaling)

# Block irrigation type -> cost_components.csv irrigation system component.
SYSTEM_COMPONENT = {
    "drip": "irrigation_system_drip",
    "micro_sprinkler": "irrigation_system_micro_sprinkler",
    "sprinkler": "irrigation_system_sprinkler",
    "flood": "irrigation_system_flood",
}


@dataclass(frozen=True)
class IndexValue:
    name: str
    value: float
    unit: str
    year: int            # the year the value comes from
    wanted_year: int     # the year that was asked for
    source: str
    source_url: str

    @property
    def is_estimate(self) -> bool:
        return self.year != self.wanted_year

    @property
    def estimate_reason(self) -> str | None:
        if not self.is_estimate:
            return None
        return f"No {self.name} index for {self.wanted_year}; the nearest year ({self.year}) is used"


class CostIndexes:
    """Yearly NASS prices-paid indexes and EIA prices from data/prices/cost_indexes.csv."""

    def __init__(self, rows: list[dict]):
        self._data: dict[str, dict[int, dict]] = {}
        for r in rows:
            self._data.setdefault(r["index_name"], {})[int(r["year"])] = r

    @classmethod
    def from_csv(cls, path: Path = COST_DIR / "cost_indexes.csv") -> "CostIndexes":
        with Path(path).open(newline="") as f:
            return cls(list(csv.DictReader(f)))

    @property
    def latest_year(self) -> int:
        return max(max(series) for series in self._data.values())

    def get(self, name: str, year: int) -> IndexValue:
        """The value for `year`, or the nearest year that has one (earlier year on a tie)."""
        series = self._data.get(name)
        if not series:
            raise PriceNotFoundError(f"No {name!r} cost index")
        found = min(series, key=lambda y: (abs(y - year), y))
        r = series[found]
        return IndexValue(name, float(r["value"]), r["unit"], found, year, r["source"], r["source_url"])


def load_cost_indexes(path: Path = COST_DIR / "cost_indexes.csv") -> CostIndexes:
    return CostIndexes.from_csv(path)


def year_used(price_mode: str, year: int, indexes: CostIndexes) -> int:
    """'current': the latest year in cost_indexes.csv for every simulated year, so only
    weather changes from year to year. 'historical': the simulated year itself."""
    if price_mode not in PRICE_MODES:
        raise ValueError(f"price_mode must be one of {PRICE_MODES}, got {price_mode!r}")
    return indexes.latest_year if price_mode == "current" else year


# ---------------------------------------------------------------- cost components

@dataclass(frozen=True)
class CostComponent:
    component: str
    basis: str                 # per_acre, per_ton or per_acre_system
    amount: float              # $/acre, $/ton or $/acre/yr in base_year dollars
    base_year: int | None      # None: not scaled (no study year known)
    index_name: str            # cost_indexes.csv name, WEIGHTED_INDEX, or "" for none
    study_yield_tpa: float | None
    region: str
    source: str = ""
    source_url: str = ""
    is_estimate: bool = False
    estimate_reason: str = ""


def load_cost_components(path: Path = COST_DIR / "cost_components.csv"
                         ) -> dict[tuple[str, str], list[CostComponent]]:
    out: dict[tuple[str, str], list[CostComponent]] = {}
    with Path(path).open(newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault((r["crop"], r["region"]), []).append(CostComponent(
                r["component"], r["basis"], float(r["amount_usd"]), int(r["base_year"]),
                r["index_name"], float(r["study_yield_tons_per_acre"]) if r["study_yield_tons_per_acre"] else None,
                r["region"], r["source"], r["source_url"], r["is_estimate"] == "true", r["estimate_reason"]))
    return out


def total_cost_component(cost_excl_water: float, region: str, source: str) -> list[CostComponent]:
    """A crop with a production cost but no component breakdown: the whole cost as one
    unscaled per-acre row, flagged as an estimate."""
    return [CostComponent("other", "per_acre", float(cost_excl_water), None, "", None, region, source,
                          is_estimate=True,
                          estimate_reason="No cost breakdown for this crop; the total study cost is used "
                                          "without index scaling")]


_SYSTEM_PART = re.compile(r"^(.*) ([\d.]+) USD / (\d+) yr$")


def system_parts(c: CostComponent) -> list[tuple[str, float, int]]:
    """(study line, installed $/acre, life years) behind a UC Davis irrigation system row:
    its yearly amount is the sum of installed / life (cost_components.csv source text)."""
    if c.basis != "per_acre_system" or "system life: " not in c.source:
        return []
    text = c.source.split("system life: ", 1)[1].rsplit(" (", 1)[0]
    parts = []
    for piece in text.split(" + "):
        m = _SYSTEM_PART.match(piece.strip())
        if not m:
            return []
        parts.append((m.group(1), float(m.group(2)), int(m.group(3))))
    if abs(round(sum(i / life for _, i, life in parts), 4) - c.amount) > 1e-9:
        raise ValueError(f"System parts {parts} do not add up to {c.amount} ({c.region} {c.component})")
    return parts


def is_ers(c: CostComponent) -> bool:
    return c.index_name == ERS_YEARLY


def components_for_year(components: list[CostComponent], year: int) -> list[CostComponent]:
    """USDA ERS rows come one set per year: keep the set for `year`, or the nearest year
    with a note. Other rows (one study year, scaled by indexes) pass through unchanged."""
    ers = [c for c in components if is_ers(c)]
    if not ers:
        return components
    found = min({c.base_year for c in ers}, key=lambda y: (abs(y - year), y))
    keep = [c for c in components if not is_ers(c) or c.base_year == found]
    if found == year:
        return keep
    note = f"; no ERS value for {year}, the nearest year ({found}) is used"
    return [replace(c, estimate_reason=c.estimate_reason + note) if is_ers(c) else c for c in keep]


def irrigation_by_crop(table: dict[tuple[str, str], list[CostComponent]]) -> dict[str, list[str]]:
    """Irrigation types with cost data for each crop: a UC Davis study for the crop (any
    conventional region) or the crop's USDA ERS rows prices that system. Other crop and
    irrigation combinations are not available."""
    by_component = {v: k for k, v in SYSTEM_COMPONENT.items()}
    out: dict[str, set[str]] = {}
    for (crop, region), rows in table.items():
        if "organic" in region.lower() or "statewide" in region.lower():
            continue
        for c in rows:
            if c.basis == "per_acre_system" and c.component in by_component:
                out.setdefault(crop, set()).add(by_component[c.component])
    order = list(SYSTEM_COMPONENT)
    return {crop: sorted(irr, key=order.index) for crop, irr in sorted(out.items())}


# ---------------------------------------------------------------- block cost

@dataclass
class CostLine:
    """One cost_components row, scaled to the year used."""
    component: CostComponent
    ratio: float                       # index[year_used] / index[base_year]
    now: IndexValue | None = None
    base: IndexValue | None = None


@dataclass
class BlockCost:
    year_used: int
    lines: list[CostLine]              # per_acre and per_ton rows
    system: CostLine | None            # irrigation system row for the block's irrigation type
    weighted_ratio: float              # ratio used for rows with no index of their own
    inputs_per_acre: float
    inputs: float
    harvest: float
    surface: float
    groundwater: float
    irrigation_system: float
    electricity: IndexValue | None
    total: float
    estimates: list[str]               # reasons any value is an estimate

    water: float = 0.0                 # surface + groundwater, to $0.01 when rounded


def dollar_weight(c: CostComponent) -> float:
    """$/acre a row stands for in the study: per_ton rows at the study yield."""
    return c.amount * (c.study_yield_tpa or 0.0) if c.basis == "per_ton" else c.amount


def _round(x: float, digits: int, rounded: bool) -> float:
    return rnd(x, digits) if rounded else x


def block_cost(
    components: list[CostComponent],
    *,
    acres: float,
    tons: float,
    irrigation: str,
    surface_af: float,
    groundwater_af: float,
    surface_price_per_af: float | None,
    well_lift_ft: float,
    pump_efficiency: float,
    indexes: CostIndexes,
    year: int,
    rounded: bool = True,
) -> BlockCost:
    """Cost of one crop block in one simulated year, given the year used for prices.

        cost             = inputs + harvest + water + irrigation_system (added in that order)
        inputs           = sum of per_acre rows x acres x index[year] / index[base_year]
        harvest          = per_ton harvest_haul x tons x diesel[year] / diesel[base_year]
        surface water    = surface acre-ft x surface $/acre-ft
        groundwater      = acre-ft x lift ft x 1.024 kWh / pump efficiency x electricity[year] $/kWh
        irrigation_system = per_acre_system row for the irrigation type x acres x ratio

    Rows with no index of their own ("other", irrigation systems) use the dollar-weighted
    average ratio of the crop's indexed rows (per_ton rows weighted at the study yield).

    rounded=True follows the steps in the calculation record: index ratios to 6
    decimals, inputs per acre and every cost part to $0.01, total to $1. rounded=False
    keeps every value exact, so the cost is linear in acres (and in tons), which the
    optimizer relies on.
    """
    for name, value, used in (("well_lift_ft", well_lift_ft, groundwater_af),
                              ("pump_efficiency", pump_efficiency, groundwater_af),
                              ("surface_water_price_per_af", surface_price_per_af, surface_af)):
        if value is None and used:
            raise ValueError(f"{name} is not set (placeholder in defaults.json)")
    estimates: dict[str, None] = {}

    def ratio_for(c: CostComponent) -> CostLine:
        if not c.index_name or c.index_name in (WEIGHTED_INDEX, ERS_YEARLY) or c.base_year is None:
            return CostLine(c, 1.0)
        now, base = indexes.get(c.index_name, year), indexes.get(c.index_name, c.base_year)
        for v in (now, base):
            if v.is_estimate:
                estimates[v.estimate_reason] = None
        return CostLine(c, _round(now.value / base.value, 6, rounded), now, base)

    lines = [ratio_for(c) for c in components if c.basis in ("per_acre", "per_ton")]
    weights = [(dollar_weight(ln.component), ln.ratio) for ln in lines if ln.now is not None]
    total_weight = sum(w for w, _ in weights)
    weighted = _round(sum(w * r for w, r in weights) / total_weight, 6, rounded) if total_weight else 1.0
    for ln in lines:
        if ln.component.index_name == WEIGHTED_INDEX:
            ln.ratio = weighted
    for c in components:
        if c.is_estimate and c.estimate_reason:
            estimates[c.estimate_reason] = None

    inputs_per_acre = _round(sum(ln.component.amount * ln.ratio for ln in lines
                                 if ln.component.basis == "per_acre"), 2, rounded)
    inputs = _round(inputs_per_acre * acres, 2, rounded)
    harvest = _round(sum(tons * ln.component.amount * ln.ratio for ln in lines
                         if ln.component.basis == "per_ton"), 2, rounded)

    wanted = SYSTEM_COMPONENT.get(irrigation)
    system_row = next((c for c in components if c.basis == "per_acre_system" and c.component == wanted), None)
    system = CostLine(system_row, weighted) if system_row else None
    irrigation_system = _round(system_row.amount * weighted * acres, 2, rounded) if system_row else 0.0

    surface = _round(surface_af * surface_price_per_af, 2, rounded) if surface_af else 0.0
    electricity = indexes.get("electricity", year)  # shown in the record even at 0 acre-ft
    groundwater = 0.0
    if groundwater_af:
        if electricity.is_estimate:
            estimates[electricity.estimate_reason] = None
        groundwater = _round(groundwater_af * well_lift_ft * KWH_PER_AF_FT / pump_efficiency
                             * electricity.value, 2, rounded)
    # The four parts, always added in this order (the calculation record does the same).
    water = _round(surface + groundwater, 2, rounded)
    total = _round(inputs + harvest + water + irrigation_system, 0, rounded)
    return BlockCost(year, lines, system, weighted, inputs_per_acre, inputs, harvest, surface,
                     groundwater, irrigation_system, electricity, total, list(estimates), water)
