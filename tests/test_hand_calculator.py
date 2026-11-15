"""Every calculation record in a Merced response can be redone by hand from its box.

Uses tests/hand_calculator.py, which has its own parser (no eval) and its own
half-up rounding, then checks inputs, sources, units and estimate tags."""

import pytest

from backend import regions, simulate as engine
from backend.schemas import SimulateRequest
from conftest import make_weather
from hand_calculator import calculate, hand_check
from test_wording import advice_in

REPORTED = {"farmer", "nasa", "nass"}


@pytest.fixture(scope="module")
def merced():
    req = SimulateRequest.model_validate({
        "location": {"lat": 37.3, "lon": -120.48, "label": "Merced, California"}, "years": [2000, 2024],
        "blocks": [
            {"id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12},
            {"id": "b2", "crop": "processing_tomatoes", "acres": 80, "irrigation": "drip", "start_month": 4, "end_month": 9},
            {"id": "b3", "crop": "corn", "acres": 15, "irrigation": "flood", "start_month": 5, "end_month": 9},
            {"id": "b4", "crop": "walnuts", "acres": 22.5, "irrigation": "micro_sprinkler", "start_month": 1,
             "end_month": 12}],
        "optional": {"budget_usd": 600000, "surface_water_share": 0.4}})
    ctx = regions.build_context({"state": "CA", "county": "Merced", "in_california": True})
    return engine.simulate(req, wx=make_weather("1999-01-01", "2024-12-31"), context=ctx)


def all_records(calcs):
    for rid, rec in calcs.items():
        yield rid, rec
        if "lb" in rec:
            yield rid + " (lb)", rec["lb"]


def test_parser_is_basic_arithmetic():
    assert calculate("2 + 3 * 4") == 14
    assert calculate("(2 + 3) * 4 / 5") == 4
    assert calculate("208000-(-5)") == 208005
    with pytest.raises(AssertionError):
        calculate("max(1, 2)")


def test_every_record_recomputes_from_its_box(merced):
    checked = sum(hand_check(rid, rec) for rid, rec in all_records(merced.calculations))
    assert len(merced.calculations) > 800
    assert checked > 2000


def test_every_input_has_value_unit_and_source(merced):
    for rid, rec in all_records(merced.calculations):
        for i in rec["inputs"]:
            assert i["value"] is not None and str(i["source"]).strip(), (rid, i)
            assert i["unit"] is not None, (rid, i)
            if i["is_estimate"]:
                assert i["estimate_reason"], (rid, i)
            elif i["kind"] not in REPORTED:
                assert i["not_estimate_reason"], (rid, i)
        assert rec["is_estimate"] == any(i["is_estimate"] for i in rec["inputs"])
        texts = [rec["label"], rec["formula_text"], rec["rounding"]] + [s["text"] for s in rec["steps"]] + [
            str(i[k]) for i in rec["inputs"] for k in ("name", "source", "estimate_reason", "not_estimate_reason")]
        assert not any("—" in t or "–" in t for t in texts), rid
        assert not advice_in(texts), rid


def test_required_breakdowns_are_spelled_out(merced):
    c = merced.calculations
    margin = c["block.b1.2010.profit"]
    names = " | ".join(i["name"] for i in margin["inputs"])
    for needed in ("Pounds per ton", "price, ", "Production cost excluding water", "Water applied", "Surface water share",
                   "Surface water price", "Groundwater share", "Well lift", "Energy to lift 1 acre-ft by 1 ft",
                   "Pump efficiency", "Electricity price", "Cents per dollar", "Almonds area"):
        assert needed in names, needed
    steps = [s["text"] for s in margin["steps"]]
    assert [t.split(":")[0] for t in steps] == [
        "Harvest", "Sales", "Production", "Surface water", "Surface water cost", "Groundwater",
        "Electricity", "Groundwater cost", "Cost", "Margin"]
    corn = c["block.b3.2010.profit"]
    assert any(i["name"] == "Corn bushel weight" and i["value"] == 56 for i in corn["inputs"])
    assert "lb/bu" in corn["steps"][1]["text"]
    pct = c["table.farm.total.margin_pct"]
    assert pct["steps"][-1]["expr"].count("/") == 1 and "100" in pct["steps"][-1]["expr"]
    avg = c["summary.avg_water_applied_af"]
    assert sum(i["name"].startswith("Farm water applied, ") for i in avg["inputs"]) == 25
    assert avg["steps"][0]["text"].startswith("Sum of 25 yearly values")
    assert avg["steps"][-1]["text"].endswith("acre-ft") and "/ 25 years" in avg["steps"][-1]["text"]
    lb = c["summary.avg_yield_tons"]["lb"]
    assert any(i["value"] == 2000 for i in lb["inputs"]) and lb["unit"] == "lb"
