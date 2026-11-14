"""Profit and loss calculations for YieldGenerator.

Main entry points:
    pumping_cost_per_af()  groundwater pumping cost in $ per acre-ft
    block_profit()         revenue, costs and profit for one block in one year

Unit handling is explicit. Prices carry the unit string they were published with
(NASS "$ / LB", "$ / TON", "$ / BU", "$ / CWT"; EIA "cents per kilowatt-hour"),
and yields carry their own unit, so a yield in tons per acre can be valued at a
price in $ per pound. Bushel conversions are crop specific (see BUSHEL_LB).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

PRICES_DIR = Path(__file__).resolve().parent.parent / "data" / "reference" / "prices"

# Energy to lift 1 acre-ft of water 1 ft at 100% efficiency, in kWh.
KWH_PER_AF_FT = 1.02

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


def load_utility_prices(path: Path = PRICES_DIR / "utilities.csv") -> PriceTable:
    return PriceTable.from_csv(path, "type")


def load_production_costs(path: Path = PRICES_DIR / "production_costs.csv") -> dict[str, float]:
    """cost_excl_water in $/acre per crop, taken from the most recent study for that crop."""
    latest: dict[str, tuple[int, float]] = {}
    with Path(path).open(newline="") as f:
        for r in csv.DictReader(f):
            if not r["cost_excl_water"] or not r["study_year"]:
                continue
            if r["unit"].replace(" ", "").lower() != "$/acre":
                raise ValueError(f"Unexpected production cost unit {r['unit']!r} for {r['crop']}")
            year = int(r["study_year"])
            if r["crop"] not in latest or year > latest[r["crop"]][0]:
                latest[r["crop"]] = (year, float(r["cost_excl_water"]))
    return {crop: cost for crop, (_, cost) in latest.items()}


def load_defaults(path: Path = PRICES_DIR / "defaults.json") -> dict:
    """Return {name: value}. Unfilled placeholders come back as None."""
    raw = json.loads(Path(path).read_text())
    return {name: entry["value"] for name, entry in raw.items()}


# ---------------------------------------------------------------- profit

@dataclass
class BlockYear:
    crop: str
    year: int
    acres: float
    relative_yield: float      # 0 to 1, from the yield model
    baseline_yield: float      # per acre, in yield_unit
    yield_unit: str            # e.g. "TON", "LB", "BU", "CWT" (per acre)
    surface_water_af: float = 0.0   # total for the block, acre-ft
    groundwater_af: float = 0.0     # total for the block, acre-ft


def block_profit(
    block: BlockYear,
    crop_prices: PriceTable,
    utility_prices: PriceTable,
    cost_excl_water_per_acre: float,
    surface_water_price_per_af: float,
    well_lift_ft: float,
    pump_efficiency: float = 0.6,
    price_mode: str = "current",
    electricity_type: str = "electricity_commercial",
) -> dict:
    """Profit for one block in one year.

    revenue = relative_yield x baseline_yield x acres x price
    costs   = cost_excl_water x acres + surface water cost + groundwater pumping cost
    """
    for name, value in (("surface_water_price_per_af", surface_water_price_per_af),
                        ("well_lift_ft", well_lift_ft)):
        if value is None:
            raise ValueError(f"{name} is not set (placeholder in defaults.json)")

    crop_price = crop_prices.get(block.crop, block.year, price_mode)
    price_unit = normalize_unit(crop_price.unit)
    yield_per_acre_in_price_unit = convert_quantity(
        block.baseline_yield, block.yield_unit, price_unit, block.crop)
    production = block.relative_yield * yield_per_acre_in_price_unit * block.acres
    revenue = production * crop_price.value

    elec = utility_prices.get(electricity_type, block.year, price_mode)
    pump_cost_af = pumping_cost_per_af(well_lift_ft, pump_efficiency, elec.value, elec.unit)

    operating_cost = cost_excl_water_per_acre * block.acres
    surface_water_cost = block.surface_water_af * surface_water_price_per_af
    groundwater_cost = block.groundwater_af * pump_cost_af
    total_cost = operating_cost + surface_water_cost + groundwater_cost

    return {
        "crop": block.crop,
        "year": block.year,
        "acres": block.acres,
        "production": production,
        "production_unit": price_unit,
        "crop_price": crop_price.value,
        "crop_price_unit": crop_price.unit,
        "crop_price_year": crop_price.year,
        "electricity_price_per_kwh": electricity_to_dollars_per_kwh(elec.value, elec.unit),
        "electricity_price_year": elec.year,
        "pumping_cost_per_af": pump_cost_af,
        "revenue": revenue,
        "operating_cost": operating_cost,
        "surface_water_cost": surface_water_cost,
        "groundwater_cost": groundwater_cost,
        "total_cost": total_cost,
        "profit": revenue - total_cost,
        "profit_per_acre": (revenue - total_cost) / block.acres if block.acres else 0.0,
    }
