import pytest

from backend import simulate as sim
from backend import yield_weight as yw
from backend.schemas import BlockOut, BlockYearOut, SimulateRequest
from conftest import make_context, make_weather


def block_out(relative_yields, crop="corn", acres=10, id="b1", start=2001):
    yearly = [
        BlockYearOut(year=start + i, crop_water_use_in=30, effective_rain_in=5,
                     irrigation_need_af=20, water_applied_af=25, relative_yield=ry,
                     heat_stress_days=0, gdd=2000, revenue=None, cost=None, profit=None)
        for i, ry in enumerate(relative_yields)
    ]
    return BlockOut(id=id, crop=crop, acres=acres, irrigation="drip", yearly=yearly)


CTX = make_context()  # corn 160 BU / ACRE -> 4.48 tons/acre, almonds 2000 LB -> 1.0


# ---------------------------------------------------------------- shared conversion

def test_median_year_gets_exactly_baseline():
    out = yw.tons_per_acre_by_year("corn", CTX, {2001: 0.8, 2002: 0.9, 2003: 1.0})
    assert out[2002] == pytest.approx(4.48)


def test_lower_relative_yield_gives_proportionally_fewer_tons():
    out = yw.tons_per_acre_by_year("corn", CTX, {2001: 0.45, 2002: 0.9, 2003: 1.0})
    assert out[2001] == pytest.approx(4.48 * 0.45 / 0.9)
    assert out[2001] / out[2002] == pytest.approx(0.5)
    assert out[2003] == pytest.approx(4.48 / 0.9)   # good year: a bit more


def test_list_input_returns_list():
    assert yw.tons_per_acre_by_year("almonds", CTX, [1.0, 0.5, 1.0]) == pytest.approx(
        [1.0, 0.5, 1.0])


def test_location_lat_lon_uses_location_context():
    # conftest patches simulate.get_location_context to make_context()
    out = yw.tons_per_acre_by_year("oats", (37.3, -120.48), [0.7, 0.7])
    assert out == pytest.approx([1.28, 1.28])


def test_zero_median_or_no_baseline_gives_nulls():
    assert yw.tons_per_acre_by_year("corn", CTX, [0.0, 0.0, 0.5]) == [None, None, None]
    assert yw.tons_per_acre_by_year("processing_tomatoes", CTX, [0.9, 1.0]) == [None, None]


# ---------------------------------------------------------------- response block

def test_block_yield_weight_math():
    notes = {}
    bw = yw.build_block(block_out([0.8, 0.9, 1.0], acres=10), CTX, notes)
    assert bw.block_id == "b1" and bw.crop == "corn" and bw.acres == 10
    assert bw.source_unit == "BU / ACRE"
    assert bw.conversion == "bu x 56 lb / 2000"
    years = {r.year: r for r in bw.yearly}
    assert years[2002].tons_per_acre == pytest.approx(4.48)
    assert years[2002].tons == pytest.approx(44.8)
    assert years[2001].tons_per_acre == pytest.approx(4.48 * 0.8 / 0.9, abs=1e-3)
    assert years[2001].relative_yield == 0.8
    assert bw.avg_tons_per_acre == pytest.approx(4.48 * 0.9 / 0.9, abs=1e-3)
    assert bw.avg_tons == pytest.approx(44.8, abs=0.01)
    assert notes == {}


def test_block_without_baseline_is_null_with_note():
    notes = {}
    bw = yw.build_block(block_out([0.9, 1.0], crop="processing_tomatoes"), CTX, notes)
    assert bw.source_unit is None and bw.conversion is None
    assert all(r.tons is None and r.tons_per_acre is None for r in bw.yearly)
    assert bw.avg_tons is None and bw.avg_tons_per_acre is None
    assert any("no baseline yield" in n for n in notes)


def test_unknown_unit_becomes_nulls_not_a_crash():
    ctx = make_context(baseline_yields={
        "corn": {"value": 10.0, "unit": "CWT / ACRE", "basis": "county", "source": "test"}})
    notes = {}
    bw = yw.build_block(block_out([0.9, 1.0]), ctx, notes)
    assert bw.source_unit == "CWT / ACRE" and bw.avg_tons is None
    assert any("Unknown yield unit" in n for n in notes)


def test_avg_yield_tons_sums_blocks_then_averages_years():
    corn = yw.build_block(block_out([0.9, 0.9], crop="corn", acres=10), CTX)        # 44.8 / yr
    almonds = yw.build_block(block_out([1.0, 0.5], crop="almonds", acres=20, id="b2"), CTX)
    # almonds median 0.75 -> 1.333 and 0.667 tons/acre -> 26.67 and 13.33 tons
    tomatoes = yw.build_block(block_out([1.0, 1.0], crop="processing_tomatoes", id="b3"), CTX)
    expected = ((44.8 + 26.667) + (44.8 + 13.333)) / 2
    assert yw.avg_yield_tons([corn, almonds, tomatoes]) == pytest.approx(expected, abs=0.01)
    assert yw.avg_yield_tons([tomatoes]) is None


# ---------------------------------------------------------------- engine wiring

def test_simulate_response_has_yield_weight_and_summary_stats():
    req = SimulateRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48, "label": "Test"},
        "years": [2001, 2004],
        "blocks": [
            {"id": "b1", "crop": "corn", "acres": 15, "irrigation": "flood",
             "start_month": 5, "end_month": 9},
            {"id": "b2", "crop": "processing_tomatoes", "acres": 5, "irrigation": "drip",
             "start_month": 4, "end_month": 8},
        ],
    })
    resp = sim.simulate(req, wx=make_weather(), context=make_context())
    assert [bw.block_id for bw in resp.yield_weight] == ["b1", "b2"]
    corn, tomatoes = resp.yield_weight
    ry = [r.relative_yield for r in resp.blocks[0].yearly]
    assert [r.relative_yield for r in corn.yearly] == ry
    for r in corn.yearly:
        assert r.tons == pytest.approx(r.tons_per_acre * 15, abs=0.01)
    assert tomatoes.avg_tons is None
    yearly_totals = [r.tons for r in corn.yearly]
    assert resp.summary_stats.avg_yield_tons == pytest.approx(
        sum(yearly_totals) / len(yearly_totals), abs=0.01)
    assert yw.ASSUMPTION in resp.assumptions
    assert any("left out: b2 (processing tomatoes)" in a for a in resp.assumptions)
