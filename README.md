# YieldGenerator

Backtest your farm against 40+ years of NASA weather data to see how your crops would have grown, how much water they needed, and where water is being lost.

## The problem

Central Valley farmers are facing groundwater pumping cuts under California's Sustainable Groundwater Management Act (SGMA). On top of that, summers are getting hotter and winters are getting warmer. Farmers need to know how their crop mix holds up in drought and heat years, and how much water it really takes to grow it.

We built YieldGenerator for the NASA Space Apps Challenge "Adapting Farms with NASA Data." Merced, CA is our test case.

## How it works

Farmers enter:

- **Location** (address, ZIP, or lat/long). We use this to pick the right NASA POWER grid cell.
- **Each crop they grow**, its acreage, and when it's grown (start and end month). Perennials are marked year-round.
- **Irrigation type** per crop (drip, sprinkler, or flood).
- **Optional extras:** soil texture, water available per year, actual water applied, past yields, water cost, and crop price.

You can grow more than one crop per year on the same block. For example, winter oats followed by summer corn. Everything shows up on a 12-month crop timeline so it's easy to see what's in the ground and when.

Then the app:

1. Pulls daily NASA POWER data for your location (max and min temperature, humidity, wind at 2 m, solar radiation, and precipitation) and caches it.
2. Calculates reference evapotranspiration (ET0) using the FAO-56 Penman-Monteith method.
3. Multiplies ET0 by FAO-56 crop coefficients (Kc) to get daily crop water use for each crop's growth stages.
4. Adjusts for irrigation efficiency and acreage to get the total water needed, in acre-feet.
5. Tracks crop growth over time with growing degree days (GDD), heat stress days, and chill hours (for orchards).
6. Estimates relative yield for each year using the FAO-33 yield response to water (Ky) method.
7. Flags likely water waste and lets you run what-if scenarios, like changing a crop, the acreage, or the irrigation type.

## Outputs

- Water needed per year, by crop
- Crop growth progress over each season (GDD, heat stress, and chill)
- Relative yield per year (for example, "82% of a normal year"), with your best, typical, and worst years called out
- Waste flags and what-if comparisons

## Data sources

| Source | What we use it for | Link |
|---|---|---|
| NASA POWER | Daily weather data going back to 1981 | https://power.larc.nasa.gov/ |
| FAO-56 | ET0 method (Penman-Monteith) and crop coefficients (Kc) | https://www.fao.org/4/x0490e/x0490e00.htm |
| FAO-33 | Yield response to water (Ky) | https://www.fao.org/4/i2800e/i2800e00.htm |
| USDA NASS Quick Stats | County yields for validation | https://quickstats.nass.usda.gov/ |

## Assumptions and limitations

- We assume orchards and vineyards are mature and fully producing. Young blocks will be overestimated.
- POWER grid cells are about 50 km wide, so results describe regional conditions, not one specific field.
- Yield losses only come from weather and water. We assume good management for nutrients, pests, and disease.
- We show relative yield unless you give us past yields to calibrate against.

## Validation plan

We'll compare the modeled yield dips in known drought years (2014, 2015, 2021, and 2022) against USDA NASS county yields for Merced County.

## MVP scope

1. Location and crop input form with the crop timeline
2. POWER download and cache
3. ET0 and crop water calculation
4. Relative yield backtest chart
5. One what-if toggle and a few waste flags

## Tech stack

- **Backend:** Python, for data processing
- **Frontend:** TBD. _(Team: add your pick here.)_

## Team

- _Name_
- _Name_
- _Name_
- _Name_

## Project layout

```
backend/     Python data processing
frontend/    Web app (TBD)
data/cache/  Cached NASA POWER downloads (not committed)
docs/        Notes and documentation
```

## License

MIT. See [LICENSE](LICENSE).
