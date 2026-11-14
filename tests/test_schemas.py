import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.schemas import BlockIn, SimulateRequest, SimulateResponse

DOCS = Path(__file__).resolve().parent.parent / "docs"

EXAMPLE_REQUEST = {
    "location": {"lat": 37.30, "lon": -120.48, "label": "Merced, CA"},
    "years": [2000, 2024],
    "price_mode": "current",
    "blocks": [
        {"id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip",
         "start_month": 1, "end_month": 12},
        {"id": "b2", "crop": "oats", "acres": 15, "irrigation": "sprinkler",
         "start_month": 11, "end_month": 4},
        {"id": "b3", "crop": "corn", "acres": 15, "irrigation": "flood",
         "start_month": 5, "end_month": 9},
    ],
    "optional": {"soil": "loam", "water_available_af": None, "water_applied_af": None,
                 "surface_water_share": 0.5},
}


def test_example_request_parses():
    req = SimulateRequest.model_validate(EXAMPLE_REQUEST)
    assert req.years == (2000, 2024)
    assert req.optional.soil == "loam"


def test_optional_defaults_when_missing():
    body = {k: v for k, v in EXAMPLE_REQUEST.items() if k != "optional"}
    req = SimulateRequest.model_validate(body)
    assert req.optional.soil == "loam"
    assert req.optional.surface_water_share == 0.5
    assert req.optional.water_available_af is None


def test_example_response_matches_schema():
    data = json.loads((DOCS / "example_response.json").read_text())
    resp = SimulateResponse.model_validate(data)
    assert len(resp.years) == len(resp.farm_totals)
    for block in resp.blocks:
        assert [y.year for y in block.yearly] == resp.years


def test_month_wrap():
    b = BlockIn(id="b2", crop="oats", acres=1, irrigation="drip", start_month=11, end_month=4)
    assert b.wraps_year
    assert b.months == [11, 12, 1, 2, 3, 4]
    full = BlockIn(id="b1", crop="almonds", acres=1, irrigation="drip", start_month=1, end_month=12)
    assert not full.wraps_year
    assert full.months == list(range(1, 13))


@pytest.mark.parametrize("patch", [
    {"years": [2024, 2000]},
    {"years": [1970, 2000]},
    {"price_mode": "future"},
    {"blocks": []},
    {"surprise": 1},
])
def test_bad_requests_rejected(patch):
    with pytest.raises(ValidationError):
        SimulateRequest.model_validate({**EXAMPLE_REQUEST, **patch})


@pytest.mark.parametrize("field,value", [
    ("crop", "bananas"), ("acres", 0), ("irrigation", "hose"), ("start_month", 13),
])
def test_bad_block_rejected(field, value):
    block = {**EXAMPLE_REQUEST["blocks"][0], field: value}
    with pytest.raises(ValidationError):
        SimulateRequest.model_validate({**EXAMPLE_REQUEST, "blocks": [block]})


def test_duplicate_block_ids_rejected():
    b = EXAMPLE_REQUEST["blocks"][0]
    with pytest.raises(ValidationError, match="unique"):
        SimulateRequest.model_validate({**EXAMPLE_REQUEST, "blocks": [b, b]})
