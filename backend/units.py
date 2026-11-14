"""Convert NASS baseline yields to US tons (2,000 lb) per acre.

Main entry point:
    to_tons_per_acre(value, unit, crop)

NASS publishes yields in different units depending on the crop: almonds in
"LB / ACRE", corn and oats in "BU / ACRE", walnuts, tomatoes and hay in
"TONS / ACRE". Harvest weight in the app is always US tons per acre, so every
baseline goes through this one function. An unknown unit raises a ValueError
instead of guessing.
"""

from __future__ import annotations

LB_PER_TON = 2000.0

# Pounds per bushel, by crop id. Standard USDA test weights from USDA ERS,
# "Weights, Measures, and Conversion Factors for Agricultural Commodities and
# Their Products", Agricultural Handbook No. 697 (1992): corn (shelled) 56 lb,
# oats 32 lb, wheat 60 lb.
BUSHEL_WEIGHT_LB = {
    "corn": 56.0,
    "oats": 32.0,
    "wheat": 60.0,
}

LB_PER_ACRE = "LB / ACRE"
BU_PER_ACRE = "BU / ACRE"
TONS_PER_ACRE = "TONS / ACRE"
SUPPORTED_UNITS = (LB_PER_ACRE, BU_PER_ACRE, TONS_PER_ACRE)


class UnknownUnitError(ValueError):
    """A yield unit or bushel crop that this module does not know how to convert."""


def _normalize(unit: str) -> str:
    """'lb/acre', ' LB / ACRE ' and 'LB  /  ACRE' all become 'LB / ACRE'."""
    parts = [p.strip() for p in str(unit).upper().split("/")]
    return " / ".join(" ".join(p.split()) for p in parts)


def bushel_weight_lb(crop: str) -> float:
    """Pounds in one bushel of `crop`. Raises UnknownUnitError for crops without one."""
    if crop not in BUSHEL_WEIGHT_LB:
        raise UnknownUnitError(
            f"No bushel weight for crop {crop!r}. Known crops: {sorted(BUSHEL_WEIGHT_LB)}.")
    return BUSHEL_WEIGHT_LB[crop]


def conversion_text(unit: str, crop: str) -> str:
    """Short description of the conversion, for example "lb / 2000"."""
    u = _normalize(unit)
    if u == LB_PER_ACRE:
        return "lb / 2000"
    if u == BU_PER_ACRE:
        return f"bu x {bushel_weight_lb(crop):g} lb / 2000"
    if u == TONS_PER_ACRE:
        return "already tons"
    raise UnknownUnitError(_unknown_message(unit))


def to_tons_per_acre(value: float, unit: str, crop: str) -> float:
    """Convert a yield in a NASS unit to US tons (2,000 lb) per acre.

    "LB / ACRE"    value / 2000
    "BU / ACRE"    value x bushel weight of the crop / 2000
    "TONS / ACRE"  unchanged
    Anything else raises UnknownUnitError (a ValueError).
    """
    u = _normalize(unit)
    if u == LB_PER_ACRE:
        return value / LB_PER_TON
    if u == BU_PER_ACRE:
        return value * bushel_weight_lb(crop) / LB_PER_TON
    if u == TONS_PER_ACRE:
        return float(value)
    raise UnknownUnitError(_unknown_message(unit))


def _unknown_message(unit: str) -> str:
    return (f"Unknown yield unit {unit!r}. Supported units: "
            + ", ".join(repr(u) for u in SUPPORTED_UNITS) + ".")
