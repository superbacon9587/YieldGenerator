"""Shared fixtures. Synthetic weather lets engine tests run without NASA POWER."""

import numpy as np
import pandas as pd
import pytest


def make_weather(start="1999-01-01", end="2005-12-31", tmax_peak=34.0, et0_peak=7.0,
                 winter_rain_mm=12.0, rain_every=6, lat=37.5, lon=-120.625):
    """Central Valley shaped weather: hot dry summers, a rain day every few winter days.

    Smooth seasonal curves peak in mid July. Rain falls only from November to March.
    """
    idx = pd.date_range(start, end, freq="D", name="date")
    doy = idx.day_of_year.to_numpy()
    season = np.cos(2 * np.pi * (doy - 196) / 365.25)  # 1 in mid July, -1 in mid January
    tmax = (tmax_peak - 11) + 11 * season
    tmin = tmax - 15
    et0 = (et0_peak + 1) / 2 + (et0_peak - 1) / 2 * season
    month = idx.month.to_numpy()
    rainy = np.isin(month, [11, 12, 1, 2, 3]) & (np.arange(len(idx)) % rain_every == 0)
    precip = np.where(rainy, winter_rain_mm, 0.0)
    wx = pd.DataFrame({"tmax_c": tmax, "tmin_c": tmin, "precip_mm_day": precip,
                       "et0_mm_day": et0}, index=idx)
    wx.attrs = {"lat": lat, "lon": lon, "elevation_m": 50.0}
    return wx


@pytest.fixture
def weather():
    return make_weather()


def make_context(**overrides):
    """A get_location_context result shaped like Merced, with no network.

    corn uses a statewide baseline and oats has no production cost, so both
    fallback paths are exercised.
    """
    ctx = {
        "state": "CA",
        "county": "Merced",
        "in_california": True,
        "cost_region": "San Joaquin Valley North",
        "baseline_yields": {
            "almonds": {"value": 2000.0, "unit": "LB / ACRE", "basis": "county", "source": "test"},
            "walnuts": {"value": 1.9, "unit": "TONS / ACRE", "basis": "county", "source": "test"},
            "corn": {"value": 160.0, "unit": "BU / ACRE", "basis": "state", "source": "test"},
            "oats": {"value": 80.0, "unit": "BU / ACRE", "basis": "county", "source": "test"},
        },
        "production_costs": {
            "almonds": {"cost_excl_water": 3000.0, "unit": "$ / ACRE",
                        "region": "San Joaquin Valley North", "source": "test"},
            "walnuts": {"cost_excl_water": 2800.0, "unit": "$ / ACRE",
                        "region": "San Joaquin Valley North", "source": "test"},
            "corn": {"cost_excl_water": 950.0, "unit": "$ / ACRE",
                     "region": "San Joaquin Valley North", "source": "test"},
        },
        "surface_water_price_per_af": 50.0,
        "data_quality": ["Corn yield uses the statewide median (no county data for Merced)."],
    }
    ctx.update(overrides)
    return ctx


@pytest.fixture(autouse=True)
def fake_location_context(monkeypatch):
    """Keep every test off the Census geocoder; tests can still pass context= directly."""
    from backend import simulate
    monkeypatch.setattr(simulate, "get_location_context", lambda lat, lon: make_context())
