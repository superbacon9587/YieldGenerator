"""Offline tests for power_client, geocode, reference and api (network calls are mocked)."""

import datetime as dt
import math

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import api, geocode, power_client, reference


# ---------------------------------------------------------------- power_client

@pytest.mark.parametrize("lat, lon, expected", [
    (37.30, -120.48, (37.5, -120.625)),
    (37.24, -120.30, (37.0, -120.0)),
    (0.0, 0.0, (0.0, 0.0)),
    (-33.87, 151.21, (-34.0, 151.25)),
    (10.0, 179.9, (10.0, -180.0)),
])
def test_snap_to_grid(lat, lon, expected):
    assert power_client.snap_to_grid(lat, lon) == expected


def test_cache_path_uses_snapped_coords():
    assert power_client.cache_path(37.5, -120.625).name == "37.5_-120.625.parquet"


def test_default_end_date():
    assert power_client.default_end_date(dt.date(2026, 11, 14)) == dt.date(2025, 12, 31)


def fake_payload(days=("20250101", "20250102")):
    values = {p: {d: 1.0 for d in days} for p in power_client.PARAMETERS}
    values["T2M_MAX"][days[1]] = -999.0
    return {
        "geometry": {"coordinates": [-120.625, 37.5, 168.17]},
        "properties": {"parameter": values},
        "header": {"fill_value": -999.0},
        "parameters": {p: {"units": u} for p, u in power_client.EXPECTED_POWER_UNITS.items()},
    }


def test_parse_power_json_replaces_fill_and_names_columns():
    df = power_client.parse_power_json(fake_payload())
    assert list(df.columns) == power_client.COLUMNS
    assert df.index.name == "date"
    assert df.index[0] == pd.Timestamp("2025-01-01")
    assert math.isnan(df.loc["2025-01-02", "tmax_c"])
    assert df.loc["2025-01-01", "tmax_c"] == 1.0
    assert df.attrs["elevation_m"] == 168.17
    assert df.attrs["units"]["solar_mj_m2_day"] == "MJ/m^2/day"


def test_parse_power_json_rejects_unit_change():
    payload = fake_payload()
    payload["parameters"]["ALLSKY_SFC_SW_DWN"]["units"] = "kW-hr/m^2/day"
    with pytest.raises(ValueError):
        power_client.parse_power_json(payload)


def test_get_daily_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(power_client, "CACHE_DIR", tmp_path)
    calls = []

    def fake_fetch(lat, lon, start, end, timeout=180):
        calls.append((lat, lon))
        return fake_payload(("20251230", "20251231"))

    monkeypatch.setattr(power_client, "fetch_power_json", fake_fetch)
    today = dt.date(2026, 3, 1)
    df1 = power_client.get_daily(37.3, -120.48, today=today)
    df2 = power_client.get_daily(37.4, -120.5, today=today)  # same grid cell
    assert calls == [(37.5, -120.625)]
    assert (tmp_path / "37.5_-120.625.parquet").exists()
    assert df2.attrs["lat"] == 37.5 and df2.attrs["elevation_m"] == 168.17
    pd.testing.assert_frame_equal(df1, df2)

    # A new year means the cache is stale and gets refetched.
    power_client.get_daily(37.3, -120.48, today=dt.date(2027, 1, 5))
    assert len(calls) == 2


# ---------------------------------------------------------------- geocode

def test_street_address_detection():
    assert geocode.looks_like_street_address("1234 Main St, Merced, CA")
    assert not geocode.looks_like_street_address("Merced, CA")


def test_open_meteo_filters_by_state(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"name": "Merced", "admin1": "California", "country": "United States",
                 "country_code": "US", "latitude": 37.30, "longitude": -120.48},
                {"name": "Merced", "admin1": "Buenos Aires", "country": "Argentina",
                 "country_code": "AR", "latitude": -34.0, "longitude": -59.0},
            ]}

    seen = {}
    monkeypatch.setattr(geocode.requests, "get",
                        lambda url, params, timeout: seen.update(params) or Resp())
    out = geocode.geocode("Merced, CA")
    assert seen["name"] == "Merced"
    assert out == [{"label": "Merced, California, United States", "lat": 37.30, "lon": -120.48}]


def test_census_falls_back_to_open_meteo(monkeypatch):
    monkeypatch.setattr(geocode, "census_geocode", lambda q: [])
    monkeypatch.setattr(geocode, "open_meteo_geocode", lambda q: [{"label": "x", "lat": 1.0, "lon": 2.0}])
    assert geocode.geocode("1 Nowhere Rd, Merced, CA") == [{"label": "x", "lat": 1.0, "lon": 2.0}]


# ---------------------------------------------------------------- reference

CROPS = ["almonds", "walnuts", "processing_tomatoes", "corn", "oats", "alfalfa_hay"]


CROP_FIELDS = {"type", "kc", "stage_days", "season_start_month", "ky", "gdd_base_c", "heat_stress_c",
               "planting_months"}
ANNUAL_ONLY_FIELDS = {"season_days"}
ANNUALS = ["processing_tomatoes", "corn", "oats"]
PERENNIALS = ["almonds", "walnuts", "alfalfa_hay"]


def test_reference_crops_complete():
    crops = reference.crops()
    assert sorted(crops) == sorted(CROPS)
    for name, raw in crops.items():
        expected = CROP_FIELDS | (ANNUAL_ONLY_FIELDS if raw["type"] == "annual" else set())
        assert set(raw) == expected, name  # also guarantees no chill fields
        for field, entry in raw.items():
            if field == "type" or entry is None:  # perennial planting_months is a bare null
                continue
            assert set(entry) == {"value", "source", "verify"}, (name, field)
            assert isinstance(entry["verify"], bool) and entry["source"], (name, field)
            if not entry["verify"]:
                assert "fao56_ch6.pdf" in entry["source"] or "fao66.pdf" in entry["source"], (name, field)
        c = reference.crop_params(name)
        assert c["type"] in ("annual", "perennial"), name
        assert set(c["kc"]) == {"ini", "mid", "end"}
        assert set(c["stage_days"]) == {"ini", "dev", "mid", "late"}
        assert 1 <= c["season_start_month"] <= 12
        assert 0 < c["ky"] < 2


def test_every_annual_has_planting_months_and_season_days():
    annuals = [name for name, raw in reference.crops().items() if raw["type"] == "annual"]
    assert sorted(annuals) == sorted(ANNUALS)
    for name in annuals:
        raw = reference.get_crop(name)
        months = reference.planting_months(name)
        assert isinstance(months, list) and months, name
        assert all(isinstance(m, int) and 1 <= m <= 12 for m in months), name
        assert len(set(months)) == len(months), name
        assert raw["planting_months"]["verify"] is True, name
        assert "UC ANR" in raw["planting_months"]["source"] or "UC Davis" in raw["planting_months"]["source"], name
        stages = reference.crop_params(name)["stage_days"]
        assert reference.season_days(name) == sum(stages.values()), name
        assert "sum" in raw["season_days"]["source"].lower(), name
    for name in PERENNIALS:
        assert reference.get_crop(name)["planting_months"] is None, name
        assert reference.planting_months(name) is None and reference.season_days(name) is None, name
        assert not reference.is_annual(name)


def test_crop_params_and_unverified():
    corn = reference.crop_params("corn")
    assert corn["kc"] == {"ini": 0.30, "mid": 1.20, "end": 0.35}
    assert corn["ky"] == 1.25
    assert corn["planting_months"] == [3, 4, 5, 6] and corn["season_days"] == 150
    assert reference.unverified_fields("corn") == ["planting_months", "gdd_base_c", "heat_stress_c"]


def test_reference_crop_keys_match_price_table():
    from backend.economics import load_crop_prices
    prices = load_crop_prices()
    for crop in CROPS:
        prices.get(crop, 2024)  # raises if the crop key is unknown


def test_reference_irrigation_and_soils():
    assert set(reference.irrigation()) == {"drip", "micro-sprinkler", "sprinkler", "flood"}
    assert set(reference.soils()) == {"sand", "loam", "clay"}
    for table in (reference.irrigation(), reference.soils()):
        for entry in table.values():
            assert entry["verify"] is True and entry["source"]
    assert 0 < reference.irrigation_efficiency("drip") <= 1
    assert reference.soil_awc_mm_per_m("loam") > reference.soil_awc_mm_per_m("sand")
    assert reference.crops() is reference.crops()  # loaded once


# ---------------------------------------------------------------- api

def test_weather_endpoint(monkeypatch):
    df = pd.DataFrame(
        {"tmean_c": [16.9, 17.0], "tmax_c": [21.5, float("nan")], "tmin_c": [12.3, 12.0],
         "rh_pct": [73.5, 70.0], "wind_2m_m_s": [2.078, 2.0], "solar_mj_m2_day": [22.07, 20.0],
         "precip_mm_day": [0.0, 1.0], "pressure_kpa": [100.1, 100.0],
         "root_zone_wetness_frac": [0.5, 0.5]},
        index=pd.DatetimeIndex(["2025-07-06", "2025-07-07"], name="date"),
    )
    df.attrs = {"lat": 50.5, "lon": 4.375, "elevation_m": 100.0, "units": dict(power_client.UNITS)}
    monkeypatch.setattr(api.power_client, "get_daily", lambda lat, lon: df)

    body = TestClient(api.app).get("/api/weather", params={"lat": 50.8, "lon": 4.35}).json()
    assert body["lat"] == 50.5 and body["dates"] == ["2025-07-06", "2025-07-07"]
    assert body["units"]["et0_mm_day"] == "mm/day"
    assert body["data"]["tmax_c"][1] is None
    assert body["data"]["et0_mm_day"][1] is None
    assert body["data"]["et0_mm_day"][0] > 0


def test_geocode_endpoint(monkeypatch):
    monkeypatch.setattr(api.geocode_mod, "geocode", lambda q: [{"label": q, "lat": 1.0, "lon": 2.0}])
    resp = TestClient(api.app).get("/api/geocode", params={"q": "Merced"})
    assert resp.json() == [{"label": "Merced", "lat": 1.0, "lon": 2.0}]
    assert TestClient(api.app).get("/api/geocode").status_code == 422
