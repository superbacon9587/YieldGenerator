import pytest
from fastapi.testclient import TestClient

from backend import simulate as sim
from backend.api import app
from conftest import make_context, make_weather

BODY = {
    "location": {"lat": 37.30, "lon": -120.48, "label": "Merced, CA"},
    "years": [2001, 2004],
    "price_mode": "current",
    "blocks": [
        {"id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip",
         "start_month": 1, "end_month": 12},
        {"id": "b2", "crop": "oats", "acres": 15, "irrigation": "sprinkler",
         "start_month": 11, "end_month": 4},
        {"id": "b3", "crop": "corn", "acres": 15, "irrigation": "flood",
         "start_month": 5, "end_month": 9},
    ],
    "optional": {"soil": "loam"},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(sim, "load_weather", lambda lat, lon: make_weather())
    return TestClient(app)


def test_simulate_endpoint(client, monkeypatch):
    # corn has a statewide baseline and oats has no production cost.
    monkeypatch.setattr(sim, "get_location_context", lambda lat, lon: make_context())
    r = client.post("/api/simulate", json=BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"location", "years", "blocks", "farm_totals", "summary",
                         "waste_flags", "assumptions", "yield_weight", "summary_stats"}
    assert data["location"]["county"] == "Merced"
    assert data["location"]["cost_region"] == "San Joaquin Valley North"
    assert data["years"] == [2001, 2002, 2003, 2004]
    oats = next(b for b in data["blocks"] if b["id"] == "b2")
    assert all(y["profit"] is None and y["revenue"] is None for y in oats["yearly"])
    corn = next(b for b in data["blocks"] if b["id"] == "b3")
    assert all(y["profit"] is not None for y in corn["yearly"])
    assert any("statewide median" in a for a in data["assumptions"])
    assert any("b2 (oats)" in a for a in data["assumptions"])
    assert any(f["block_id"] == "b3" and f["type"] == "irrigation_method"
               for f in data["waste_flags"])


def test_minimal_body_uses_defaults(client):
    body = {k: v for k, v in BODY.items() if k not in ("optional", "price_mode")}
    r = client.post("/api/simulate", json=body)
    assert r.status_code == 200, r.text


def test_bad_request_is_422(client):
    r = client.post("/api/simulate", json={**BODY, "blocks": []})
    assert r.status_code == 422


def test_years_without_weather_is_422(client):
    r = client.post("/api/simulate", json={**BODY, "years": [2010, 2012]})
    assert r.status_code == 422
    assert "available 1999-01-01 to 2005-12-31" in r.json()["detail"]


def test_context_service_down_is_502(client, monkeypatch):
    import requests

    def down(lat, lon):
        raise requests.ConnectionError("census down")
    monkeypatch.setattr(sim, "get_location_context", down)
    r = client.post("/api/simulate", json=BODY)
    assert r.status_code == 502


def test_cors_allows_vite_dev_server(client):
    r = client.options("/api/simulate", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
