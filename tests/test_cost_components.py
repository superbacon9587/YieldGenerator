"""Checks on data/prices/cost_components.csv, built by scripts/build_cost_components.py."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "data" / "prices" / "cost_components.csv"
PRODUCTION_COSTS = ROOT / "data" / "reference" / "prices" / "production_costs.csv"
COST_INDEXES = ROOT / "data" / "prices" / "cost_indexes.csv"

EXPECTED_INDEX = {
    "seed": "seeds",
    "fertilizer": "fertilizer",
    "chemicals": "chemicals",
    "labor": "wages",
    "machinery_fuel": "diesel",
    "harvest_haul": "diesel",
}

components = pd.read_csv(COMPONENTS, keep_default_na=False)
production = pd.read_csv(PRODUCTION_COSTS)
CROP_REGIONS = list(production[["crop", "region"]].itertuples(index=False, name=None))


def test_columns():
    assert list(components.columns) == ["crop", "region", "component", "basis", "amount_usd",
                                        "base_year", "index_name", "source", "source_url"]
    assert set(components["basis"]) <= {"per_acre", "per_ton", "per_acre_system"}
    assert components["source_url"].str.match(r"https://(coststudies|coststudyfiles)\.ucdavis\.edu/").all()


@pytest.mark.parametrize("crop,region", CROP_REGIONS)
def test_components_sum_to_operating_cost_excl_water(crop, region):
    rows = components[(components["crop"] == crop) & (components["region"] == region)
                      & (components["basis"] == "per_acre")]
    assert not rows.empty, f"no components for {crop} / {region}"
    expected = production.loc[(production["crop"] == crop) & (production["region"] == region),
                              "cost_excl_water"].item()
    assert rows["amount_usd"].astype(float).sum() == pytest.approx(expected, abs=1.0)


def test_no_water_component():
    assert not components["component"].str.contains("water", case=False).any()


def test_index_names():
    for component, index in EXPECTED_INDEX.items():
        assert (components.loc[components["component"] == component, "index_name"] == index).all(), component
    known = set(pd.read_csv(COST_INDEXES)["index_name"])
    used = set(components["index_name"]) - {""}
    assert used <= known


def test_other_rows_say_what_they_contain():
    other = components[components["component"] == "other"]
    assert other["source"].str.contains("includes").all()


def test_one_row_per_component():
    assert not components.duplicated(["crop", "region", "component"]).any()
