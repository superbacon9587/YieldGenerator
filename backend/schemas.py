"""Request and response models for POST /api/simulate.

This file is the code version of docs/api_contract.md. If a field changes here,
update that document and tell the frontend owner first.

Units:
    water at the farm and block level is in acre-feet (af)
    water at the crop level is in inches per acre (in)
    money is in US dollars
    temperatures behind gdd and heat_stress_days are in degrees C

Season years: a block whose season wraps the new year (start_month > end_month,
for example 11 to 4) is reported under the year it ends in. Oats planted in
November 2014 and harvested in April 2015 are the 2015 season.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------- shared vocab

Crop = Literal[
    "almonds",
    "walnuts",
    "processing_tomatoes",
    "corn",
    "oats",
    "alfalfa_hay",
]
"""Crop ids. They match the crop column in data/reference/prices/crop_prices.csv."""

PERENNIALS: frozenset[str] = frozenset({"almonds", "walnuts", "alfalfa_hay"})

Irrigation = Literal["drip", "micro_sprinkler", "sprinkler", "flood"]
Soil = Literal["sand", "loam", "clay"]
PriceMode = Literal["current", "historical"]
WasteFlagType = Literal[
    "irrigation_method",   # losses vs drip for the same crop
    "over_applied",        # water_applied_af given and above modeled need
    "rain_covered",        # water applied in weeks where rain already met crop need
    "low_holding_soil",    # high water crop on sand
]
YieldBasis = Literal["county", "state"]

# NASA POWER daily data (backend/power_client.py) starts in 1984. A wrapping season ending in 1984 would
# need 1983 weather, so the earliest safe start year is 1985 for those blocks;
# the engine checks that, the schema only checks the outer bound.
MIN_YEAR = 1984
MAX_YEAR = 2100


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- request

class LocationIn(_Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field(default="", max_length=200)


class BlockIn(_Strict):
    id: str = Field(min_length=1, max_length=32, description='Short id such as "b1"')
    crop: Crop
    acres: float = Field(gt=0)
    irrigation: Irrigation
    start_month: int = Field(ge=1, le=12)
    end_month: int = Field(ge=1, le=12)

    @property
    def wraps_year(self) -> bool:
        """True when the season crosses Dec 31, for example 11 to 4 (Nov to Apr)."""
        return self.start_month > self.end_month

    @property
    def months(self) -> list[int]:
        """Months in the field, in season order. 11 to 4 gives [11, 12, 1, 2, 3, 4]."""
        if self.wraps_year:
            return list(range(self.start_month, 13)) + list(range(1, self.end_month + 1))
        return list(range(self.start_month, self.end_month + 1))


class OptionalIn(_Strict):
    soil: Soil = "loam"
    water_available_af: float | None = Field(
        default=None, ge=0,
        description="Cap on total water the farm can apply per year, acre-ft.")
    water_applied_af: float | None = Field(
        default=None, ge=0,
        description="Water the farm reports it actually applied per year, acre-ft.")
    surface_water_share: float = Field(
        default=0.5, ge=0, le=1,
        description="Fraction of applied water from surface water; the rest is groundwater.")


class SimulateRequest(_Strict):
    location: LocationIn
    years: tuple[int, int] = Field(description="[start, end], inclusive")
    price_mode: PriceMode = "current"
    blocks: list[BlockIn] = Field(min_length=1)
    optional: OptionalIn = Field(default_factory=OptionalIn)

    @field_validator("years")
    @classmethod
    def _check_years(cls, v: tuple[int, int]) -> tuple[int, int]:
        start, end = v
        if not (MIN_YEAR <= start <= end <= MAX_YEAR):
            raise ValueError(
                f"years must be [start, end] with {MIN_YEAR} <= start <= end, got {list(v)}")
        return v

    @model_validator(mode="after")
    def _unique_block_ids(self) -> "SimulateRequest":
        ids = [b.id for b in self.blocks]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"block ids must be unique, repeated: {dupes}")
        return self


# ---------------------------------------------------------------- response

class LocationOut(BaseModel):
    label: str
    grid_cell: tuple[float, float] = Field(
        description="[lat, lon] of the NASA POWER grid cell center used for weather")
    county: str | None = Field(default=None, description="None outside California")
    cost_region: str | None = Field(default=None, description="None outside California")


class BlockYearOut(BaseModel):
    year: int
    crop_water_use_in: float = Field(description="Full crop ET (ETc) for the season, inches")
    effective_rain_in: float = Field(description="Rain the crop could use, inches")
    irrigation_need_af: float = Field(description="Net irrigation need for the block, acre-ft")
    water_applied_af: float = Field(
        description="Gross water applied for the block (net / efficiency, capped if "
                    "water_available_af is set), acre-ft")
    relative_yield: float = Field(ge=0, le=1, description="1.0 is a full, unstressed yield")
    heat_stress_days: int = Field(ge=0)
    gdd: float = Field(ge=0, description="Growing degree days over the season, degree C days")
    revenue: float | None = Field(description="None when baseline yield or price is missing")
    cost: float | None = Field(description="None when production cost is missing")
    profit: float | None


class BlockOut(BaseModel):
    id: str
    crop: Crop
    acres: float
    irrigation: Irrigation
    yearly: list[BlockYearOut]


class FarmYearOut(BaseModel):
    year: int
    water_applied_af: float
    relative_yield: float = Field(
        ge=0, le=1, description="Acre-weighted mean of block relative yields")
    revenue: float | None = Field(description="Sum over blocks; None if any block is None")
    cost: float | None
    profit: float | None


class SummaryOut(BaseModel):
    best_year: int
    worst_year: int
    typical_year: int = Field(description="Median year by the same ranking metric")
    drought_years: list[int] = Field(
        description="Known California drought years inside the requested range")


class WasteFlagOut(BaseModel):
    block_id: str
    type: WasteFlagType
    message: str = Field(description="Plain English, shown to the farmer as is")
    estimated_af_per_year: float = Field(ge=0)
    estimated_cost_per_year: float | None = Field(
        ge=0, description="Dollars per year; None when water prices are unavailable")


class YieldWeightYearOut(BaseModel):
    year: int
    tons_per_acre: float | None = Field(
        description="US tons (2,000 lb) per acre. None when the crop has no baseline yield")
    tons: float | None = Field(description="tons_per_acre x acres")
    relative_yield: float = Field(ge=0, le=1, description="Same value as blocks[].yearly[]")


class BlockYieldWeightOut(BaseModel):
    block_id: str
    crop: Crop
    acres: float
    source_unit: str | None = Field(
        description='Unit of the NASS baseline yield, for example "BU / ACRE". '
                    "None when the crop has no baseline yield")
    conversion: str | None = Field(
        description='Short text such as "lb / 2000". None when there is no weight')
    yearly: list[YieldWeightYearOut]
    avg_tons: float | None = Field(description="Mean of yearly tons")
    avg_tons_per_acre: float | None = Field(description="Mean of yearly tons_per_acre")


class SummaryStatsOut(BaseModel):
    avg_yield_tons: float | None = Field(
        default=None,
        description="Average over years of the total harvest weight of all blocks, US tons")


class SimulateResponse(BaseModel):
    location: LocationOut
    years: list[int]
    blocks: list[BlockOut]
    farm_totals: list[FarmYearOut]
    summary: SummaryOut
    waste_flags: list[WasteFlagOut]
    assumptions: list[str]
    yield_weight: list[BlockYieldWeightOut] = Field(
        default_factory=list, description="Harvest weight per block and year (Part C)")
    summary_stats: SummaryStatsOut = Field(default_factory=SummaryStatsOut)


# ---------------------------------------------------------------- location context
# Shape returned by get_location_context(lat, lon) in backend/regions.py.
# Marco owns that function. These models document and validate its output;
# they do not implement it.

class BaselineYield(BaseModel):
    value: float = Field(gt=0)
    unit: str = Field(description='NASS style, for example "LB / ACRE" or "TONS / ACRE"')
    basis: YieldBasis
    source: str


class ProductionCost(BaseModel):
    cost_excl_water: float = Field(ge=0)
    unit: str = Field(description='"$ / ACRE"')
    region: str
    source: str


class LocationContext(BaseModel):
    state: str | None = Field(description="Two-letter code; None outside the US")
    county: str | None
    in_california: bool
    cost_region: str | None
    baseline_yields: dict[str, BaselineYield] = Field(
        description="Keyed by crop id. A crop can be missing when no data exists.")
    production_costs: dict[str, ProductionCost] = Field(
        description="Keyed by crop id. A crop can be missing when no data exists.")
    surface_water_price_per_af: float | None
    data_quality: list[str] = Field(default_factory=list)
