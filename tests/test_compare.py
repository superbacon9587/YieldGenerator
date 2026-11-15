import pytest
from fastapi.testclient import TestClient

from backend import compare as cmp
from backend import power_client
from backend import simulate as sim
from backend.api import app
from conftest import make_weather
from test_simulate import block, request


def farm(irrigation="flood", acres=10, crop="corn", **optional):
    months = {"start": 1, "end": 12} if crop in ("almonds", "walnuts") else {}
    return request([block("b1", crop=crop, acres=acres, irrigation=irrigation, **months)],
                   **optional).model_dump()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(sim, "load_weather", lambda lat, lon: make_weather())
    return TestClient(app)


# ---------------------------------------------------------------- ranking

def test_rank_higher_first_with_ties_and_none_last():
    assert cmp.rank([10, 30, None, 30, 5], lower_first=False) == [3, 1, 5, 1, 4]


def test_rank_lower_first_for_water():
    assert cmp.rank([200.0, 150.0, None], lower_first=True) == [2, 1, 3]


# ---------------------------------------------------------------- endpoint

def test_compare_ranks_by_profit_by_default(client):
    # Walnuts have cost data for micro-sprinkler and flood irrigation.
    body = {"configs": [{"name": "Flood walnuts", "farm": farm("flood", crop="walnuts")},
                        {"name": "Micro walnuts", "farm": farm("micro_sprinkler", crop="walnuts")}]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ranked_by"] == "avg_profit"
    profits = [x["summary_stats"]["avg_profit"] for x in data["results"]]
    assert None not in profits and profits == sorted(profits, reverse=True)
    assert [x["rank"] for x in data["results"]] == [1, 2]
    for x in data["results"]:
        assert set(x) == {"name", "summary_stats", "budget", "rank", "calculations"}
        assert x["summary_stats"]["years_count"] == 4


def test_compare_ranks_water_lower_first(client):
    body = {"ranked_by": "avg_water_applied_af",
            "configs": [{"name": "Flood", "farm": farm("flood")},
                        {"name": "Drip", "farm": farm("drip")},
                        {"name": "Sprinkler", "farm": farm("sprinkler")}]}
    data = client.post("/api/compare", json=body).json()
    assert [x["name"] for x in data["results"]] == ["Drip", "Sprinkler", "Flood"]
    water = [x["summary_stats"]["avg_water_applied_af"] for x in data["results"]]
    assert water == sorted(water)


def test_compare_total_profit_and_yield_options(client):
    for ranked_by in ("total_profit", "avg_relative_yield"):
        body = {"ranked_by": ranked_by,
                "configs": [{"name": "Small", "farm": farm(acres=5)},
                            {"name": "Large", "farm": farm(acres=50)}]}
        r = client.post("/api/compare", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["ranked_by"] == ranked_by


def test_compare_includes_budget(client):
    body = {"configs": [{"name": "A", "farm": farm(budget_usd=1)},
                        {"name": "B", "farm": farm()}]}
    data = client.post("/api/compare", json=body).json()
    by_name = {x["name"]: x for x in data["results"]}
    assert by_name["A"]["budget"]["years_over_budget"] == [2001, 2002, 2003, 2004]
    assert by_name["B"]["budget"]["budget_usd"] is None


@pytest.mark.parametrize("n", [1, 7])
def test_compare_rejects_wrong_count(client, n):
    body = {"configs": [{"name": f"S{i}", "farm": farm()} for i in range(n)]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 422
    assert "2 to 6 setups" in r.text


def test_compare_rejects_duplicate_names_and_bad_rank(client):
    dupes = {"configs": [{"name": "Same", "farm": farm()}, {"name": "Same", "farm": farm()}]}
    assert client.post("/api/compare", json=dupes).status_code == 422
    bad = {"ranked_by": "drawdown",
           "configs": [{"name": "A", "farm": farm()}, {"name": "B", "farm": farm()}]}
    assert client.post("/api/compare", json=bad).status_code == 422


def test_compare_weather_gap_is_422(client):
    body = {"configs": [{"name": "A", "farm": farm()},
                        {"name": "B", "farm": {**farm(), "years": [2010, 2012]}}]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 422


# ---------------------------------------------------------------- meta

def test_meta(client, monkeypatch):
    import datetime as dt
    monkeypatch.setattr(power_client, "default_end_date", lambda today=None: dt.date(2025, 12, 31))
    data = client.get("/api/meta").json()
    assert data == {"first_year": 1985, "last_full_year": 2025, "presets": [5, 10, 20, 30, 40],
                    "irrigation_by_crop": sim.irrigation_by_crop()}
    assert data["irrigation_by_crop"]["processing_tomatoes"] == ["drip"]
    assert data["irrigation_by_crop"]["oats"] == ["flood"]


def test_meta_drops_presets_longer_than_history(client, monkeypatch):
    import datetime as dt
    monkeypatch.setattr(power_client, "default_end_date", lambda today=None: dt.date(2010, 12, 31))
    assert client.get("/api/meta").json()["presets"] == [5, 10, 20]


def test_compare_rejects_ui_fields_inside_farm_with_clear_422(client):
    """The backend stays strict: UI-only fields in a farm are a 422 naming each field."""
    dirty = dict(farm("drip"), period="20", optimize={"objective": "profit"})
    body = {"configs": [{"name": "A", "farm": dirty},
                        {"name": "B", "farm": farm("flood")}]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]
    bad = {(tuple(e["loc"]), e["type"]) for e in errors}
    assert (("body", "configs", 0, "farm", "period"), "extra_forbidden") in bad
    assert (("body", "configs", 0, "farm", "optimize"), "extra_forbidden") in bad
    assert all("Extra inputs are not permitted" in e["msg"] for e in errors)
