"""Checks on data/prices/cost_indexes.csv, built by scripts/fetch_cost_indexes.py."""

from pathlib import Path

import pandas as pd
import pytest

CSV = Path(__file__).resolve().parent.parent / "data" / "prices" / "cost_indexes.csv"
NASS_INDEXES = ["fertilizer", "chemicals", "seeds", "fuels", "wages"]
ALL_INDEXES = NASS_INDEXES + ["electricity", "diesel"]
FIRST_YEAR = 1994


@pytest.fixture(scope="module")
def indexes() -> pd.DataFrame:
    return pd.read_csv(CSV)


def test_columns(indexes):
    assert list(indexes.columns) == ["year", "index_name", "value", "unit", "source", "source_url"]
    assert set(indexes["index_name"]) == set(ALL_INDEXES)
    assert indexes["value"].notna().all()
    assert indexes["source_url"].str.match(r"https://(quickstats\.nass\.usda\.gov|www\.eia\.gov)").all()


@pytest.mark.parametrize("name", ALL_INDEXES)
def test_every_year_from_1994_to_latest(indexes, name):
    latest = int(indexes["year"].max())
    years = set(indexes.loc[indexes["index_name"] == name, "year"])
    missing = sorted(set(range(FIRST_YEAR, latest + 1)) - years)
    assert not missing, f"{name} missing years {missing}"


@pytest.mark.parametrize("name", ALL_INDEXES)
def test_no_duplicate_years(indexes, name):
    years = indexes.loc[indexes["index_name"] == name, "year"]
    assert not years.duplicated().any(), f"{name} duplicated years {sorted(years[years.duplicated()])}"


@pytest.mark.parametrize("name", NASS_INDEXES)
def test_nass_2011_is_100(indexes, name):
    row = indexes[(indexes["index_name"] == name) & (indexes["year"] == 2011)]
    assert len(row) == 1
    assert row["value"].iloc[0] == pytest.approx(100.0)
