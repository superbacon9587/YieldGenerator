"""Harvest weight in US tons for each block and year.

Main entry points:
    tons_per_acre_by_year(crop, location, relative_yields)
        The one shared conversion from relative yield to tons per acre. The
        scenario comparisons and the optimizer should call this so every part of
        the app turns relative yield into weight the same way.
    build_yield_weight(blocks, context)
        The "yield_weight" list in the /api/simulate response.
    avg_yield_tons(yield_weight)
        Average total harvest per year across all blocks, for summary_stats.

Scaling against a typical year:
    The county median yield from NASS already reflects typical growing
    conditions, not perfect ones. relative_yield is a fraction of a full,
    unstressed yield. So a year is scaled against the block's own typical year:

        tons_per_acre = baseline_tons_per_acre x relative_yield / median relative_yield

    where public backtests use the median from the uncapped-water reference run over the fixed 1991–2020 complete-season reference (or available record when absent), independent of display years and water caps. Standalone helpers without a reference retain their legacy median behavior. A typical
    year shows the typical county harvest, a drought year shows less, and a good
    year shows a bit more. When the median is 0 or missing, or the crop has no
    baseline yield, the weights are null.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import median

from backend import units
from backend.schemas import BlockOut, BlockYieldWeightOut, YieldWeightYearOut

ASSUMPTION = ("Harvest weight uses the county or statewide median yield and an uncapped-water reference calibration. The reference is held fixed when applying a farm water limit; yield losses are not normalized away.")


# ---------------------------------------------------------------- shared conversion

def baseline_tons_per_acre(crop: str, context: Mapping) -> float | None:
    """Baseline yield for the crop in tons per acre, or None when there is none.

    Raises units.UnknownUnitError when the baseline uses a unit we cannot convert.
    """
    base = (context.get("baseline_yields") or {}).get(crop)
    if not base or base.get("value") is None:
        return None
    return units.to_tons_per_acre(base["value"], base["unit"], crop)


def _median_or_none(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return median(present) if present else None


def scale_to_tons(base_tpa: float | None, relative_yields: Sequence[float | None],
                  reference_relative_yield: float | None = None
                  ) -> list[float | None]:
    """tons_per_acre for each relative yield, scaled against their median."""
    typical = reference_relative_yield if reference_relative_yield is not None else _median_or_none(relative_yields)
    if base_tpa is None or not typical:
        return [None] * len(relative_yields)
    return [None if ry is None else base_tpa * ry / typical for ry in relative_yields]


def _context_for(location) -> Mapping:
    """Accept a location context dict, or anything with lat and lon."""
    if isinstance(location, Mapping) and "baseline_yields" in location:
        return location
    if isinstance(location, Mapping):
        lat, lon = location["lat"], location["lon"]
    elif isinstance(location, Sequence) and len(location) == 2:
        lat, lon = location
    else:
        lat, lon = location.lat, location.lon
    from backend import simulate  # imported here: simulate imports this module
    return simulate.get_location_context(lat, lon)


def tons_per_acre_by_year(crop: str, location, relative_yields):
    """Tons per acre for each year of one block.

    crop             crop id, for example "corn"
    location         a get_location_context result, or a location with lat and lon
                     (a dict, a (lat, lon) pair, or a LocationIn)
    relative_yields  {year: relative_yield} or a list of relative yields covering
                     every backtest year of the block (the median is taken over them)

    Returns the same shape as relative_yields ({year: tons} or a list), with None
    where the weight is unknown.
    """
    base = baseline_tons_per_acre(crop, _context_for(location))
    if isinstance(relative_yields, Mapping):
        years = list(relative_yields)
        tons = scale_to_tons(base, [relative_yields[y] for y in years])
        return dict(zip(years, tons))
    return scale_to_tons(base, list(relative_yields))


# ---------------------------------------------------------------- response

def _round(x: float | None, digits: int) -> float | None:
    return None if x is None else round(x, digits)


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def build_block(block: BlockOut, context: Mapping, notes: dict | None = None,
                reference_relative_yield: float | None = None
                ) -> BlockYieldWeightOut:
    """Yield weight for one block. Unknown units become nulls plus a note."""
    base_info = (context.get("baseline_yields") or {}).get(block.crop) or {}
    source_unit = base_info.get("unit")
    label = block.crop.replace("_", " ")
    try:
        base = baseline_tons_per_acre(block.crop, context)
        conversion = units.conversion_text(source_unit, block.crop) if base is not None else None
    except units.UnknownUnitError as exc:
        base, conversion = None, None
        if notes is not None:
            notes[f"Block {block.id} ({label}) has no harvest weight: {exc}"] = None
    if base is None and not base_info and notes is not None:
        notes[f"Block {block.id} ({label}) has no baseline yield, so its harvest weight "
              "is shown as no data."] = None

    ry = [r.relative_yield for r in block.yearly]
    tpa = scale_to_tons(base, ry, reference_relative_yield)
    yearly = [
        YieldWeightYearOut(
            year=r.year,
            tons_per_acre=_round(t, 3),
            tons=_round(None if t is None else t * block.acres, 2),
            relative_yield=r.relative_yield,
        )
        for r, t in zip(block.yearly, tpa)
    ]
    return BlockYieldWeightOut(
        block_id=block.id,
        crop=block.crop,
        acres=block.acres,
        source_unit=source_unit,
        conversion=conversion,
        reference_relative_yield=reference_relative_yield if reference_relative_yield is not None else _median_or_none(ry),
        yearly=yearly,
        avg_tons=_round(_mean([None if t is None else t * block.acres for t in tpa]), 2),
        avg_tons_per_acre=_round(_mean(tpa), 3),
    )


def build_yield_weight(blocks: Sequence[BlockOut], context: Mapping,
                       notes: dict | None = None, *,
                       reference_relative_yields: Mapping | None = None) -> list[BlockYieldWeightOut]:
    """The "yield_weight" response list, one entry per block in request order."""
    return [build_block(b, context, notes, (reference_relative_yields or {}).get(b.id)) for b in blocks]


def avg_yield_tons(yield_weight: Sequence[BlockYieldWeightOut]) -> float | None:
    """Average over years of the farm's total harvest weight in tons.

    Each year adds up the blocks that have a weight. Null when no block has one.
    """
    totals: dict[int, float] = {}
    for bw in yield_weight:
        for row in bw.yearly:
            if row.tons is not None:
                totals[row.year] = totals.get(row.year, 0.0) + row.tons
    return _round(_mean(list(totals.values())), 2)


def assumptions(yield_weight: Sequence[BlockYieldWeightOut], notes: Mapping) -> list[str]:
    """Plain sentences for the response assumptions list."""
    out = [ASSUMPTION] + list(notes)
    with_weight = [bw for bw in yield_weight if bw.avg_tons is not None]
    if with_weight and len(with_weight) < len(yield_weight):
        left_out = [f"{bw.block_id} ({bw.crop.replace('_', ' ')})"
                    for bw in yield_weight if bw.avg_tons is None]
        out.append("Average harvest per year only adds up blocks with a harvest weight "
                   "(left out: " + ", ".join(left_out) + ").")
    return out
