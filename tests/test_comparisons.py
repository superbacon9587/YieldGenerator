import time
from copy import deepcopy

import pytest

from backend import reference, simulate as engine
from backend.comparisons import build_comparisons
from backend.schemas import SimulateRequest
from conftest import make_context, make_weather


def farm(years=(2001, 2004), cap=None):
    return SimulateRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48}, "years": years,
        "blocks": [
            {"id": "almond", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12},
            {"id": "oat", "crop": "oats", "acres": 15, "irrigation": "flood", "start_month": 11, "end_month": 4},
            {"id": "corn", "crop": "corn", "acres": 15, "irrigation": "flood", "start_month": 5, "end_month": 9},
        ], "optional": {"water_available_af": cap}})


def test_irrigation_coverage_sorting_missing_prices_and_immutability():
    request = farm()
    before = request.model_dump()
    result = engine.simulate(request, wx=make_weather(), context=make_context())
    for block in request.blocks:
        rows = [r for r in result.comparisons if r.block_id == block.id and r.kind == "irrigation"]
        # Only irrigation types with cost data for the crop are offered.
        assert {r.alternative.irrigation for r in rows} == set(engine.irrigation_by_crop()[block.crop]) - {block.irrigation}
        values = [r.avg_profit_change for r in rows if r.avg_profit_change is not None]
        assert values == sorted(values, reverse=True)
        assert all(r.current.irrigation == block.irrigation for r in rows)
        assert all("One-time cost of converting" in r.excludes for r in rows)
    # Oats (USDA ERS cost, flood only) and corn (flood only) have no irrigation alternatives.
    assert not [r for r in result.comparisons if r.block_id in ("oat", "corn") and r.kind == "irrigation"]
    micro = next(r for r in result.comparisons if r.block_id == "almond" and r.alternative.irrigation == "micro_sprinkler")
    assert micro.avg_water_change_af > 0 and micro.avg_profit_change is not None  # drip uses less water
    assert request.model_dump() == before


def test_planting_windows_wrap_and_perennials(monkeypatch):
    entries = deepcopy(reference.crops())
    entries["oats"]["planting_months"] = {"value": [10, 11, 12], "source": "test only", "verify": True}
    entries["almonds"]["planting_months"] = [2]
    entries["corn"]["planting_months"] = None  # isolate the oats wrap case
    monkeypatch.setattr(reference, "crops", lambda: entries)
    result = engine.simulate(farm(), wx=make_weather(), context=make_context())
    planting = [r for r in result.comparisons if r.kind == "planting_window"]
    assert {(r.alternative.start_month, r.alternative.end_month) for r in planting} == {(10, 3), (12, 5)}
    assert all(r.crop == "oats" for r in planting)


@pytest.mark.parametrize("cap", [None, 50])
def test_comparison_matches_full_farm_rerun(cap):
    request, weather, context = farm(cap=cap), make_weather(), make_context()
    baseline = engine.simulate(request, wx=weather, context=context)
    row = next(r for r in baseline.comparisons if r.block_id == "almond" and r.alternative.irrigation == "micro_sprinkler")
    changed = request.model_copy(deep=True)
    changed.blocks[0].irrigation = "micro_sprinkler"
    actual = engine.simulate(changed, wx=weather, context=context, include_comparisons=False)
    original = baseline.blocks[0].yearly
    alternative = actual.blocks[0].yearly
    assert row.avg_water_change_af == pytest.approx(sum(b.water_applied_af-a.water_applied_af for a,b in zip(original, alternative))/len(original), abs=.001)
    assert row.avg_relative_yield_change_pts == pytest.approx(100*sum(b.relative_yield-a.relative_yield for a,b in zip(original, alternative))/len(original), abs=.001)
    assert row.avg_profit_change == pytest.approx(sum(b.profit-a.profit for a,b in zip(original, alternative))/len(original), abs=.01)
    assert row.worst_year_profit_change == min(b.profit for b in alternative)-min(a.profit for a in original)
    if cap is not None:
        assert all(y.water_applied_af <= cap+.1 for y in actual.farm_totals)
        assert "redistribution" in row.excludes


def test_external_data_loaded_once(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "load_weather", lambda *args: calls.append("weather") or make_weather())
    monkeypatch.setattr(engine, "get_location_context", lambda *args: calls.append("context") or make_context())
    result = engine.simulate(farm())
    assert result.comparisons
    assert calls == ["weather", "context"]


def test_four_block_twenty_year_runtime(monkeypatch):
    request = farm(years=(2000, 2019))
    request.blocks.append(request.blocks[2].model_copy(update={"id": "corn2", "acres": 5}))
    weather, context = make_weather("1999-01-01", "2019-12-31"), make_context()
    baseline = engine.simulate(request, wx=weather, context=context, include_comparisons=False)
    entries = deepcopy(reference.crops())
    entries["corn"]["planting_months"] = [4, 5, 6]
    entries["oats"]["planting_months"] = [10, 11, 12]
    monkeypatch.setattr(reference, "crops", lambda: entries)
    start = time.perf_counter()
    rows = build_comparisons(request, baseline, wx=weather, context=context)
    elapsed = time.perf_counter() - start
    # Only priced irrigation types: almonds drip -> micro-sprinkler (1); oats and corn are
    # flood only, so just their 2 other planting months each (oats, corn, corn2).
    assert len(rows) == 1 + 2 + 2 + 2
    assert elapsed < 3, f"Comparison overhead: {elapsed:.2f}s"


def test_unavailable_shifted_season_is_explained(monkeypatch):
    entries = deepcopy(reference.crops())
    entries["corn"]["planting_months"] = [5, 11]
    monkeypatch.setattr(reference, "crops", lambda: entries)
    request = farm(years=(2000, 2001))
    weather = make_weather("2000-01-01", "2001-12-31")
    request.blocks = [request.blocks[2]]
    result = engine.simulate(request, wx=weather, context=make_context())
    assert not any(r.kind == "planting_window" for r in result.comparisons)
    assert any("unavailable weather" in note for note in result.assumptions)


def test_partial_profit_is_unavailable_not_a_zero_or_partial_average():
    from backend.comparisons import _metrics
    result = engine.simulate(farm(), wx=make_weather(), context=make_context(), include_comparisons=False)
    original = result.blocks[0]
    changed = original.model_copy(deep=True)
    changed.yearly[0].profit = None
    metrics = _metrics(original, changed)
    assert metrics["avg_profit_change"] is None
    assert metrics["worst_year_profit_change"] is None
    assert metrics["avg_water_change_af"] == 0
