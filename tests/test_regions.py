"""Tests for county_lookup, regions and GET /api/context (Census Geocoder is mocked)."""

import json

import pytest
from fastapi.testclient import TestClient

from backend import api, county_lookup, regions

MERCED = (37.30, -120.48)
SACRAMENTO = (38.58, -121.49)
RENO_NV = (39.53, -119.81)
OCEAN = (30.0, -140.0)


def _geos(stusab, county):
    return {
        "States": [{"STUSAB": stusab, "NAME": "x"}],
        "Counties": [{"BASENAME": county, "NAME": f"{county} County"}],
    }


FAKE_CENSUS = {
    MERCED: _geos("CA", "Merced"),
    SACRAMENTO: _geos("CA", "Sacramento"),
    RENO_NV: _geos("NV", "Washoe"),
    OCEAN: {},
}

EXPECTED_KEYS = {"state", "county", "in_california", "cost_region", "baseline_yields",
                 "production_costs", "surface_water_price_per_af", "data_quality"}
YIELD_KEYS = {"value", "unit", "basis", "source"}
COST_KEYS = {"cost_excl_water", "unit", "region", "source"}


@pytest.fixture(autouse=True)
def fake_census(monkeypatch):
    calls = []

    def fake_fetch(lat, lon):
        calls.append((lat, lon))
        return FAKE_CENSUS[(lat, lon)]

    monkeypatch.setattr(county_lookup, "fetch_geographies", fake_fetch)
    county_lookup.clear_cache()
    yield calls
    county_lookup.clear_cache()


# ---------------------------------------------------------------- county_lookup

def test_lookup_merced():
    assert county_lookup.lookup(*MERCED) == {"state": "CA", "county": "Merced", "in_california": True}


def test_lookup_is_cached(fake_census):
    county_lookup.lookup(*MERCED)
    county_lookup.lookup(*MERCED)
    assert len(fake_census) == 1


def test_lookup_offshore_point():
    assert county_lookup.lookup(*OCEAN) == {"state": None, "county": None, "in_california": False}


def test_parse_falls_back_to_name_without_county_suffix():
    geos = {"States": [{"STUSAB": "CA"}], "Counties": [{"NAME": "San Luis Obispo County"}]}
    assert county_lookup.parse_geographies(geos)["county"] == "San Luis Obispo"


# ---------------------------------------------------------------- regions, real data files

def test_merced_context():
    ctx = regions.get_location_context(*MERCED)
    assert ctx["state"] == "CA"
    assert ctx["county"] == "Merced"
    assert ctx["in_california"] is True
    assert ctx["cost_region"] == "San Joaquin Valley North"
    assert ctx["surface_water_price_per_af"] == 50
    # Merced has 29 years of NASS county corn yields.
    assert ctx["baseline_yields"]["corn"]["basis"] == "county"
    assert ctx["baseline_yields"]["corn"]["unit"] == "BU / ACRE"
    # SJV North has its own alfalfa study; almonds fall back to a neighbor region.
    assert ctx["production_costs"]["alfalfa_hay"]["region"] == "San Joaquin Valley North"
    assert ctx["production_costs"]["almonds"]["region"] == "Sacramento Valley"
    assert "San Joaquin Valley North has no loaded almond study" in ctx["production_costs"]["almonds"]["source"]


def test_sacramento_context():
    ctx = regions.get_location_context(*SACRAMENTO)
    assert ctx["county"] == "Sacramento"
    assert ctx["cost_region"] == "Sacramento Valley"
    assert ctx["production_costs"]["walnuts"]["region"] == "Sacramento Valley"


def test_nevada_point_is_outside_california_with_warning():
    ctx = regions.get_location_context(*RENO_NV)
    assert ctx["in_california"] is False
    assert ctx["state"] == "NV"
    assert regions.OUTSIDE_CA_NOTE in ctx["data_quality"]
    assert "outside California" in regions.OUTSIDE_CA_NOTE
    assert all(y["basis"] == "state" for y in ctx["baseline_yields"].values())
    assert ctx["production_costs"]  # California costs still supplied


def test_missing_county_crop_falls_back_to_statewide():
    """NASS has no county walnut series, so Merced walnuts use the state median."""
    ctx = regions.get_location_context(*MERCED)
    walnut = ctx["baseline_yields"]["walnuts"]
    assert walnut["basis"] == "state"
    assert "California statewide" in walnut["source"]
    assert "Walnut yield uses the statewide median (no county data for Merced)." in ctx["data_quality"]


def test_crop_without_any_cost_study_is_left_out_with_note():
    ctx = regions.get_location_context(*MERCED)
    assert "oats" not in ctx["production_costs"]
    assert any("oat" in n and "production cost" in n for n in ctx["data_quality"])


@pytest.mark.parametrize("point", [MERCED, SACRAMENTO, RENO_NV, OCEAN])
def test_shape_exactly_matches_contract(point):
    ctx = regions.get_location_context(*point)
    assert set(ctx) == EXPECTED_KEYS
    assert isinstance(ctx["in_california"], bool)
    assert isinstance(ctx["surface_water_price_per_af"], float)
    assert isinstance(ctx["data_quality"], list) and all(isinstance(n, str) for n in ctx["data_quality"])
    for y in ctx["baseline_yields"].values():
        assert set(y) == YIELD_KEYS
        assert isinstance(y["value"], (int, float)) and y["basis"] in ("county", "state")
    for c in ctx["production_costs"].values():
        assert set(c) == COST_KEYS
        assert isinstance(c["cost_excl_water"], float) and c["unit"] == "$ / ACRE"


def test_every_california_county_has_a_region():
    data = json.loads(regions.REGIONS_FILE.read_text())
    assert len(data["counties"]) == 58
    assert set(data["counties"].values()) <= set(data["regions"])
    assert set(data["nearest_regions"]) == set(data["regions"])


def test_no_em_dashes_in_new_files():
    for path in (regions.REGIONS_FILE, regions.PRICES_DIR / "production_costs.csv",
                 regions.PRICES_DIR / "defaults.json"):
        assert chr(0x2014) not in path.read_text()


# ---------------------------------------------------------------- regions, synthetic tables

def _write(path, text):
    path.write_text(text)
    return path


@pytest.fixture
def tiny_tables(tmp_path):
    county = "county,crop,year,yield,unit,source\n" + "".join(
        f"Yolo,corn,{2000 + i},{180 + i},BU / ACRE,s\n" for i in range(12)
    ) + "".join(f"Fresno,corn,{2000 + i},100,BU / ACRE,s\n" for i in range(5))
    state = "crop,year,yield,unit,source\n" + "".join(
        f"corn,{2000 + i},{170 + i},BU / ACRE,s\n" for i in range(3)
    )
    costs = ("crop,region,study_year,cost_per_acre,water_cost_per_acre,cost_excl_water,unit,source\n"
             "corn,Sacramento Valley,2015,1118,168,950,$/acre,a.pdf p. 11\n"
             "corn,Sacramento Valley,2010,900,100,800,$/acre,old.pdf p. 9\n"
             "corn,California statewide (organic),2020,1,0,1,$/acre,org.pdf p. 1\n")
    defaults = {"surface_water_price_per_af": {"value": 50, "by_region": {
        "Sacramento Valley": {"value": 18}, "San Joaquin Valley North": {"value": 50},
        "San Joaquin Valley South": {"value": 150}}}}
    return regions.load_tables(
        county_csv=_write(tmp_path / "c.csv", county),
        state_csv=_write(tmp_path / "s.csv", state),
        costs_csv=_write(tmp_path / "p.csv", costs),
        defaults_json=_write(tmp_path / "d.json", json.dumps(defaults)),
        regions_json=regions.REGIONS_FILE,
    )


def test_county_median_with_ten_or_more_years(tiny_tables):
    ctx = regions.build_context({"state": "CA", "county": "Yolo", "in_california": True},
                                tables=tiny_tables, crops=["corn"])
    assert ctx["baseline_yields"]["corn"] == {
        "value": 185.5, "unit": "BU / ACRE", "basis": "county",
        "source": "USDA NASS Quick Stats survey yield, Yolo County CA, median of 12 years, 2000-2011",
    }
    assert ctx["production_costs"]["corn"]["cost_excl_water"] == 950.0  # latest study wins
    assert ctx["surface_water_price_per_af"] == 18.0


def test_county_with_too_few_years_uses_state(tiny_tables):
    ctx = regions.build_context({"state": "CA", "county": "Fresno", "in_california": True},
                                tables=tiny_tables, crops=["corn"])
    assert ctx["baseline_yields"]["corn"]["basis"] == "state"
    assert ctx["baseline_yields"]["corn"]["value"] == 171.0
    assert "Corn yield uses the statewide median (only 5 years of county data for Fresno)." in ctx["data_quality"]
    # SJV South has no corn row here, so the nearest region with one is used.
    assert ctx["production_costs"]["corn"]["region"] == "Sacramento Valley"


def test_crop_with_no_yield_data_is_left_out(tiny_tables):
    ctx = regions.build_context({"state": "CA", "county": "Yolo", "in_california": True},
                                tables=tiny_tables, crops=["corn", "walnuts"])
    assert "walnuts" not in ctx["baseline_yields"]
    assert "walnuts" not in ctx["production_costs"]
    assert any("walnut" in n and "baseline yield" in n for n in ctx["data_quality"])


# ---------------------------------------------------------------- api

def test_api_context_route():
    client = TestClient(api.app)
    resp = client.get("/api/context", params={"lat": MERCED[0], "lon": MERCED[1]})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == EXPECTED_KEYS
    assert body["cost_region"] == "San Joaquin Valley North"


def test_api_context_validates_input():
    client = TestClient(api.app)
    assert client.get("/api/context", params={"lat": 200, "lon": 0}).status_code == 422
