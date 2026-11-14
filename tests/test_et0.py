import math

import pandas as pd
import pytest

from backend.et0 import et0_fao56


def one_day(date: str, **values) -> pd.DataFrame:
    df = pd.DataFrame(values, index=pd.DatetimeIndex([date], name="date"))
    return df


def test_et0_matches_hand_calculation():
    """Inputs from FAO-56 Example 18 (Uccle, Brussels, 6 July), with mean RH
    instead of RHmax/RHmin because that is what POWER provides.

    Inputs: lat 50.80 N, z = 100 m, P = 100.1 kPa, Tmax 21.5, Tmin 12.3 degC,
    RHmean 73.5 %, u2 2.078 m/s, Rs 22.07 MJ/m2/day, day of year 187.

    Hand calculation (FAO-56 equation numbers in brackets):
      Tmean = (21.5 + 12.3) / 2                          = 16.9 degC     [9]
      Delta = 4098 e0(16.9) / (16.9 + 237.3)^2           = 0.1226 kPa/C  [13]
      gamma = 0.665e-3 x 100.1                           = 0.06657 kPa/C [8]
      e0(21.5) = 2.5645, e0(12.3) = 1.4306 kPa                           [11]
      es = (2.5645 + 1.4306) / 2                         = 1.9976 kPa    [12]
      ea = 0.735 x 1.9976                                = 1.4682 kPa    [19]
      dr = 0.9671, delta = 0.3954 rad, ws = 2.1081 rad                   [23-25]
      Ra                                                 = 41.09 MJ/m2/d [21]
      Rso = (0.75 + 2e-5 x 100) x 41.09                  = 30.90         [37]
      Rns = (1 - 0.23) x 22.07                           = 16.99         [38]
      Rnl = 34.76 x (0.34 - 0.14 sqrt(1.4682))
                  x (1.35 x 22.07 / 30.90 - 0.35)        = 3.64          [39]
      Rn  = 16.99 - 3.64                                 = 13.36         [40]
      ET0 = [0.408 x 0.1226 x 13.36
             + 0.06657 x 900 / 289.9 x 2.078 x (1.9976 - 1.4682)]
            / [0.1226 + 0.06657 x (1 + 0.34 x 2.078)]
          = (0.6681 + 0.2273) / 0.2362                   = 3.79 mm/day   [6]
    """
    df = one_day(
        "2025-07-06",  # day of year 187, as in the FAO example
        tmax_c=21.5, tmin_c=12.3, tmean_c=16.0, rh_pct=73.5, wind_2m_m_s=2.078,
        solar_mj_m2_day=22.07, pressure_kpa=100.1,
    )
    et0 = et0_fao56(df, lat=50.80, elevation_m=100.0)
    assert et0.iloc[0] == pytest.approx(3.79, abs=0.01)


def test_et0_ignores_power_t2m_and_uses_attrs():
    """Tmean comes from (Tmax + Tmin) / 2, so tmean_c has no effect, and lat and
    elevation are read from df.attrs when not passed."""
    base = dict(tmax_c=21.5, tmin_c=12.3, rh_pct=73.5, wind_2m_m_s=2.078,
                solar_mj_m2_day=22.07, pressure_kpa=100.1)
    a = one_day("2025-07-06", tmean_c=10.0, **base)
    b = one_day("2025-07-06", tmean_c=20.0, **base)
    for df in (a, b):
        df.attrs = {"lat": 50.80, "elevation_m": 100.0}
    assert et0_fao56(a).iloc[0] == pytest.approx(et0_fao56(b).iloc[0])


def test_et0_missing_input_gives_nan():
    df = one_day("2025-07-06", tmax_c=21.5, tmin_c=12.3, rh_pct=float("nan"),
                 wind_2m_m_s=2.078, solar_mj_m2_day=22.07, pressure_kpa=100.1)
    assert math.isnan(et0_fao56(df, lat=50.8, elevation_m=100).iloc[0])


def test_et0_requires_location():
    df = one_day("2025-07-06", tmax_c=21.5, tmin_c=12.3, rh_pct=73.5,
                 wind_2m_m_s=2.078, solar_mj_m2_day=22.07, pressure_kpa=100.1)
    with pytest.raises(ValueError):
        et0_fao56(df)
