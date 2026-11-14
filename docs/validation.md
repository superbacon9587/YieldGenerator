# Backtest validation: Merced County

We ran the YieldGenerator engine for 1 acre of each crop at Merced, CA (lat 37.30, lon -120.48) and compared its yearly relative yield with real USDA NASS yields for Merced County. Rerun it with `python scripts/validate_backtest.py`. The chart is [validation.png](validation.png).

**Short version:** the model does not explain year-to-year changes in Merced yields. Correlations are weak, between -0.32 and +0.34. Its drought-year dips point the right way for corn and for the 2021 and 2022 tomato crops, but they are much smaller than the real drops. This is the result we expected from a weather-and-water-only model that assumes full irrigation, and the reasons are below.

## How we compared

- **Modeled:** relative yield from `backend/simulate.py` with full irrigation and loam soil. Seasons are corn May to September, oats November to April, and processing tomatoes April to August.
- **Actual:** the NASS yield divided by that crop's median Merced yield (the yield anomaly). NASS yields also climb over the decades from better varieties and practices, which the model never tries to capture. So we also compare against yield divided by its linear trend.
- **Data:** corn and oats come from `data/validation/merced_yields.csv`. Processing tomatoes come from the Merced rows of `data/validation/ca_county_yields.csv`, the only Merced series that covers all four drought years.

## Results

| Crop | Years compared | Range | r vs yield / median | r vs yield / trend | Drought years in data | Modeled, drought vs other years | Actual (trend removed), drought vs other years |
|---|---|---|---|---|---|---|---|
| Corn (grain) | 29 | 1984-2016 | +0.10 | +0.34 | 2015 | 98% vs 99% | 83% vs 101% |
| Oats | 25 | 1985-2009 | -0.32 | -0.32 | none | n/a | n/a |
| Processing tomatoes | 18 | 1991-2025 | -0.04 | +0.18 | 2014, 2015, 2021, 2022 | 98% vs 99% | 97% vs 101% |

r is the Pearson correlation between modeled and actual. 1 is a perfect match and 0 is no relationship. With 18 to 29 years, an r below about 0.4 is not statistically meaningful.

## What matched

- **Corn, 2015 and 2016.** The model shows small dips in both years, and real corn yields dropped sharply (17 and 36 percent below trend).
- **Tomatoes, 2021 and 2022.** The model's dips (to 96.5 and 98.5 percent) line up with real yields below trend (93 and 87 percent). 2021 is the model's lowest tomato year.
- **Removing the long-term trend helps.** Once it is removed, corn's correlation rises from +0.10 to +0.34. That is a hint that weather explains some of what is left over, but it is too weak to rely on.

## What did not match

- **The model's swings are too small.** Modeled relative yield stays between about 96 and 100 percent, while real yields move 10 to 30 percent from year to year. Under full irrigation, only heat can cut modeled yield, and our heat rule is capped and mild.
- **Tomatoes, 2014 and 2015.** Real tomato yields were above trend in the worst drought years, while the model shows small dips. Growers with water likely protected high-value tomatoes, and tomato prices and contracts drive how many acres get planted.
- **Oats run backwards (r = -0.32).** Merced oats are mostly rain-fed or cut for hay, and NASS stopped reporting them after 2009. The model irrigates them fully, so it misses the dry-winter failures, such as 2001 at about half of normal yield.
- **No Merced corn or oats data for 2021 and 2022**, so those droughts are only tested on tomatoes.

## Why, honestly

1. **Water cuts are not in the default run.** In 2014, 2015, 2021 and 2022, Merced farms got less surface water. The model only shows that when a water cap is set (`water_available_af`). The app's "Cut water 25 percent" what-if shows those losses, but this validation runs with full water.
2. **Management, prices, and pests.** NASS county yields mix in fertilizer, varieties, pest years, planting dates, and which fields were planted at all. Drought years also change which fields get planted. The model assumes good management.
3. **Regional weather.** NASA POWER grid cells are about 50 km wide, so local heat and frost do not show up exactly.
4. **County averages.** One NASS number covers every field in Merced County, while the model runs one typical acre.
5. **Placeholder crop numbers.** Several Ky values, heat thresholds, and season dates in `crops.json` are still marked as needing a check against FAO sources.

## What this means for the demo

YieldGenerator is useful for **water**: how much each crop needs in a given year, how much more a drought year needs, and how much a different irrigation system or crop would save. It is also useful for showing **what happens when water is cut**. It should **not** be presented as predicting a specific year's yield. When a water cap is set, yield losses follow FAO-33, a widely used and published method, but this check did not test those cases against real data.
