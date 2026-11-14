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
