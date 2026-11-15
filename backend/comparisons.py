"""One-entry counterfactuals using the existing whole-farm simulation.

Metrics describe the changed crop entry, after whole-farm water allocation.
No suitability or financial recommendation is inferred from these differences.
"""

from statistics import mean
from typing import get_args

from backend import reference
from backend.schemas import ComparisonOut, Irrigation, PERENNIALS


def _system(block):
    return {k: getattr(block, k) for k in ("irrigation", "start_month", "end_month")}


def _alternatives(block):
    from backend.simulate import irrigation_available
    for irrigation in get_args(Irrigation):
        # Only irrigation types with cost data for the crop are offered.
        if irrigation != block.irrigation and irrigation_available(block.crop, irrigation):
            yield "irrigation", block.model_copy(update={"irrigation": irrigation})
    if block.crop in PERENNIALS:
        return
    months = reference.crop_params(block.crop).get("planting_months")
    if not isinstance(months, list):
        return
    valid = {m for m in months if isinstance(m, int) and not isinstance(m, bool) and 1 <= m <= 12}
    for month in sorted(valid):
        if month != block.start_month:
            end = (block.end_month + month - block.start_month - 1) % 12 + 1
            yield "planting_window", block.model_copy(update={"start_month": month, "end_month": end})


def _metrics(original, alternative):
    before = {row.year: row for row in original.yearly}
    after = {row.year: row for row in alternative.yearly}
    if before.keys() != after.keys():
        raise ValueError("Comparison years must match the baseline")
    years = sorted(before)
    complete = all(before[y].profit is not None and after[y].profit is not None for y in years)
    return {
        "avg_profit_change": round(mean(after[y].profit - before[y].profit for y in years), 2) if complete else None,
        "avg_relative_yield_change_pts": round(100 * mean(after[y].relative_yield - before[y].relative_yield for y in years), 3),
        "avg_water_change_af": round(mean(after[y].water_applied_af - before[y].water_applied_af for y in years), 3),
        "worst_year_profit_change": round(min(after[y].profit for y in years) - min(before[y].profit for y in years), 2) if complete else None,
    }


def build_comparisons(farm, baseline_response, *, wx=None, context=None):
    """Keep the baseline immutable and load external data at most once.

    Missing planting windows are deliberately skipped, never guessed. Alternatives
    needing unavailable weather are omitted and explained in baseline assumptions.
    """
    from backend import simulate as engine

    if wx is None:
        wx = engine.load_weather(farm.location.lat, farm.location.lon)
    if context is None:
        context = engine.get_location_context(farm.location.lat, farm.location.lon)
    originals = {block.id: block for block in baseline_response.blocks}
    comparisons = []
    for index, block in enumerate(farm.blocks):
        rows = []
        for kind, changed in _alternatives(block):
            candidate = farm.model_copy(deep=True)
            candidate.blocks[index] = changed
            # With no shared water cap, entries are independent in this engine.
            # Evaluate only the changed entry, with its actual acreage, to avoid
            # recomputing unchanged daily balances. Capped farms still rerun all
            # entries because their allocation and yields can change together.
            if farm.optional.water_available_af is None:
                candidate.blocks = [changed]
            try:
                response = engine.simulate(candidate, wx=wx, context=context, include_comparisons=False)
            except engine.WeatherUnavailableError:
                note = f"Comparison for {block.id} starting in month {changed.start_month} was omitted because its season needs unavailable weather."
                if note not in baseline_response.assumptions:
                    baseline_response.assumptions.append(note)
                continue
            alternative = next(b for b in response.blocks if b.id == block.id)
            excludes = ("One-time cost of converting to the new system is not included; its yearly system cost "
                        "(installed cost over its life) is, where a UC Davis study prices it." if kind == "irrigation"
                        else "Market timing and field operations for a different planting month are not included.")
            if farm.optional.water_available_af is not None:
                excludes += " Changes describe this crop entry; water redistribution can also affect other entries."
            rows.append(ComparisonOut(block_id=block.id, crop=block.crop, kind=kind,
                                      current=_system(block), alternative=_system(changed),
                                      excludes=excludes, **_metrics(originals[block.id], alternative)))
        rows.sort(key=lambda row: (row.avg_profit_change is None, -(row.avg_profit_change or 0)))
        comparisons.extend(rows)
    return comparisons
