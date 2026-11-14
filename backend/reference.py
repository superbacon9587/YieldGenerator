"""Crop, irrigation and soil reference tables from data/reference/*.json.

Each file is read once per process (functools.cache). Every entry carries
"source" and "verify"; verify=true means the number is a placeholder that still
needs checking against the cited source. In crops.json each field (except
"type") is its own {value, source, verify} record; crop_params() strips those.

Crop keys match data/reference/prices/crop_prices.csv: almonds, walnuts,
processing_tomatoes, corn, oats, alfalfa_hay.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"


def _load(name: str) -> dict:
    raw = json.loads((REFERENCE_DIR / name).read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@cache
def crops() -> dict[str, dict]:
    return _load("crops.json")


@cache
def irrigation() -> dict[str, dict]:
    return _load("irrigation.json")


@cache
def soils() -> dict[str, dict]:
    return _load("soils.json")


def get_crop(name: str) -> dict:
    """Raw crops.json entry: every field except "type" is {value, source, verify}."""
    try:
        return crops()[name]
    except KeyError:
        raise KeyError(f"Unknown crop {name!r}. Known: {sorted(crops())}") from None


def crop_params(name: str) -> dict:
    """Crop entry with sources stripped, e.g. {"type": ..., "kc": {"ini": .., ...}, "ky": 1.25, ...}."""
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v)
            for k, v in get_crop(name).items()}


def unverified_fields(name: str) -> list[str]:
    """Fields of a crop still marked verify=true."""
    return [k for k, v in get_crop(name).items() if isinstance(v, dict) and v.get("verify")]


def irrigation_efficiency(system: str) -> float:
    try:
        return irrigation()[system]["efficiency"]
    except KeyError:
        raise KeyError(f"Unknown irrigation system {system!r}. Known: {sorted(irrigation())}") from None


def soil_awc_mm_per_m(texture: str) -> float:
    try:
        return soils()[texture]["awc_mm_per_m"]
    except KeyError:
        raise KeyError(f"Unknown soil texture {texture!r}. Known: {sorted(soils())}") from None
