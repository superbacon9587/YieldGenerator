"""Checks on data/prices/cost_components.csv, built by scripts/build_cost_components.py."""

from pathlib import Path

import re

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

ALL = pd.read_csv(COMPONENTS, keep_default_na=False, dtype={"is_estimate": str})
WEIGHTED = "weighted_inputs"
ERS_INDEX = "ers_yearly"
IS_ERS = ALL["source"].str.startswith("USDA ERS Commodity Costs and Returns")
components = ALL[~IS_ERS]   # UC Davis study rows; the USDA ERS rows are checked below
ers = ALL[IS_ERS]
production = pd.read_csv(PRODUCTION_COSTS)
CROP_REGIONS = sorted(set(components[["crop", "region"]].itertuples(index=False, name=None))
                      | set(production[["crop", "region"]].itertuples(index=False, name=None)))
ERS_RAW = ROOT / "data" / "raw" / "ers" / "oats.csv"


def study_file(source: str) -> str:
    """'UC Davis cost study x.pdf, Costs and Returns ...' -> 'x.pdf'."""
    return re.search(r"cost study (\S+?\.pdf)", source).group(1)


def production_row(crop: str, region: str) -> pd.Series:
    """The production_costs row a crop and region is built from: its own, or for an
    estimate, the row of the study it borrows (same study file)."""
    own = production[(production["crop"] == crop) & (production["region"] == region)]
    if len(own):
        return own.iloc[0]
    rows = components[(components["crop"] == crop) & (components["region"] == region)]
    pdf = study_file(rows["source"].iloc[0])
    return production[(production["crop"] == crop)
                      & (production["source"].str.startswith(pdf + " "))].iloc[0]


def test_columns():
    assert list(ALL.columns) == ["crop", "region", "component", "basis", "amount_usd",
                                        "base_year", "index_name", "study_yield_tons_per_acre", "source",
                                        "source_url", "is_estimate", "estimate_reason"]
    assert set(components["basis"]) <= {"per_acre", "per_ton", "per_acre_system", "excluded"}
    assert components["source_url"].str.match(r"https://(coststudies|coststudyfiles)\.ucdavis\.edu/").all()


@pytest.mark.parametrize("crop,region", CROP_REGIONS)
def test_components_sum_to_operating_cost_excl_water(crop, region):
    rows = components[(components["crop"] == crop) & (components["region"] == region)
                      & components["basis"].isin(["per_acre", "per_ton", "excluded"])]
    assert not rows.empty, f"no components for {crop} / {region}"
    per_acre = rows["amount_usd"].astype(float) * rows["study_yield_tons_per_acre"].astype(float).where(
        rows["basis"] == "per_ton", 1.0)
    expected = production_row(crop, region)["cost_excl_water"]
    assert per_acre.sum() == pytest.approx(expected, abs=1.0)


def test_no_water_component():
    assert not ALL["component"].str.contains("water", case=False).any()


def test_index_names():
    for component, index in EXPECTED_INDEX.items():
        assert (components.loc[components["component"] == component, "index_name"] == index).all(), component
    known = set(pd.read_csv(COST_INDEXES)["index_name"])
    used = set(components.loc[components["basis"] != "excluded", "index_name"]) - {WEIGHTED}
    assert used <= known
    unindexed = components[~components["component"].isin(list(EXPECTED_INDEX))
                           & (components["basis"] != "excluded")]
    assert (unindexed["index_name"] == WEIGHTED).all()


def test_land_rent_is_never_charged():
    rent = components[components["component"] == "land_rent"]
    assert (rent["basis"] == "excluded").all()
    charged = components[components["basis"] != "excluded"]
    assert not charged["source"].str.contains("Land Rent", case=False).any()


def test_harvest_is_per_ton_and_systems_are_yearly():
    assert (components.loc[components["component"] == "harvest_haul", "basis"] == "per_ton").all()
    systems = components[components["component"].str.startswith("irrigation_system_")]
    assert (systems["basis"] == "per_acre_system").all()
    assert systems["source"].str.contains(" / system life: ").all()
    # Yearly cost, not the installed cost: no system costs more than $200/acre/yr.
    assert systems["amount_usd"].astype(float).max() < 200
    assert (components["study_yield_tons_per_acre"].astype(float) > 0).all()


def test_other_rows_say_what_they_contain():
    other = components[components["component"] == "other"]
    assert other["source"].str.contains("includes").all()


def test_one_row_per_component():
    assert not components.duplicated(["crop", "region", "component"]).any()


@pytest.mark.parametrize("crop,region", CROP_REGIONS)
def test_base_year_is_study_year(crop, region):
    rows = components[(components["crop"] == crop) & (components["region"] == region)]
    assert (rows["base_year"].astype(int) == int(production_row(crop, region)["study_year"])).all()


def test_conventional_regions_never_use_organic_studies():
    conventional = components[~components["region"].str.contains("organic", case=False)]
    used = conventional["source"].map(study_file)
    assert not used.str.contains("organic").any(), sorted(set(used[used.str.contains("organic")]))
    organic_files = production.loc[production["region"].str.contains("organic"), "source"].str.split(" p. ").str[0]
    assert not used.isin(organic_files).any()


def test_estimates_are_marked():
    assert set(ALL["is_estimate"]) <= {"true", "false"}
    estimates = components[components["is_estimate"] == "true"]
    assert (estimates["estimate_reason"] != "").all()
    assert (components.loc[components["is_estimate"] == "false", "estimate_reason"] == "").all()
    alfalfa_south = components[(components["crop"] == "alfalfa_hay")
                               & (components["region"] == "San Joaquin Valley South")]
    assert len(alfalfa_south) and (alfalfa_south["is_estimate"] == "true").all()
    assert (alfalfa_south["estimate_reason"] == "No conventional SJV South alfalfa study available; "
                                                "using the nearest region's study.").all()



# ---------------------------------------------------------------- USDA ERS (oats)

def test_ers_rows_are_oats_flood_only_and_marked():
    assert set(ers["crop"]) == {"oats"} and set(ers["region"]) == {"U.S. total (ERS)"}
    assert (ers["index_name"] == ERS_INDEX).all()
    assert (ers["source_url"] == "https://www.ers.usda.gov/data-products/commodity-costs-and-returns").all()
    assert (ers["is_estimate"] == "true").all()
    operating = ers[ers["basis"] == "per_acre"]
    assert (operating["estimate_reason"]
            == "National/regional ERS average; no California oats cost study available").all()
    systems = ers[ers["basis"] == "per_acre_system"]
    assert set(systems["component"]) == {"irrigation_system_flood"}
    assert (systems["amount_usd"].astype(float) == 0).all()
    assert systems["source"].str.contains("USDA ERS whole-farm average per planted acre already includes "
                                          "these costs; no separate irrigation system line.").all()
    assert (systems["estimate_reason"] == "National ERS average; no California oats cost study.").all()
    assert not ers.duplicated(["component", "base_year"]).any()


@pytest.mark.skipif(not ERS_RAW.exists(), reason="data/raw/ers/oats.csv not downloaded (data/raw is gitignored)")
def test_ers_components_add_up_to_ers_operating_cost_each_year():
    raw = pd.read_csv(ERS_RAW, encoding="utf-8-sig")
    raw = raw[(raw["Region"] == "U.S. total") & (raw["Category"] == "Operating costs")]
    assert not raw["Item"].str.contains("irrigat|water", case=False).any()  # nothing to count twice
    total = raw[raw["Item"].str.strip() == "Total, operating costs"].set_index("Year")["Value"]
    sums = ers[ers["basis"] == "per_acre"].astype({"amount_usd": float, "base_year": int}).groupby(
        "base_year")["amount_usd"].sum()
    assert list(sums.index) == list(range(2005, 2026))
    for year, value in sums.items():
        assert value == pytest.approx(total[year], abs=0.05), year
