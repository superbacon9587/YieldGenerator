# Simulate API contract

`POST /api/simulate` runs the backtest for one farm and returns yearly water use, relative yield, harvest weight, and money per block, plus farm totals, a summary, summary stats, budget and land checks, system comparisons, and waste flags.

The Pydantic models in [backend/schemas.py](../backend/schemas.py) are the code version of this document. A full sample response is in [example_response.json](example_response.json). Its numbers look realistic, but they were made up for the sample and do not come from the engine.

**Changing a field:** tell the other side first, then update this file and `backend/schemas.py` in the same commit.

## Units and conventions

| Thing | Unit |
|---|---|
| Water for a block or the farm | acre-feet (`_af`) |
| Water for the crop (per acre) | inches (`_in`) |
| Money | US dollars, rounded to whole dollars |
| `gdd` | growing degree days, degree C days |
| `relative_yield` | fraction, 0 to 1 (1.0 is a full, unstressed yield) |
| Harvest weight | US tons (2,000 lb), `tons` and `tons_per_acre` |

- **Months wrap around the new year.** `start_month: 11, end_month: 4` means November through April. `start_month: 1, end_month: 12` means year-round (use this for perennials).
- **Season year.** A season that crosses the new year counts in the year it ends. Oats planted November 2014 and harvested April 2015 are the 2015 season.
- **Weather data starts in 1984 and ends December 31 of last year.** A block that wraps the new year needs the previous year's weather, so its earliest season year is 1985. A range the weather does not cover gets a `422` error that names the available dates.
- **Null money.** `revenue`, `cost`, and `profit` can be `null` when a crop has no baseline yield, price, or production cost for the location. Water and yield are still filled in. The UI should show "No price data", not $0. Farm money totals add up only the blocks that have money, and `assumptions` names any block left out. A farm money total is `null` only when no block has money that year.

## Request

```json
{
  "location": { "lat": 37.30, "lon": -120.48, "label": "Merced, CA" },
  "years": [2000, 2024],
  "price_mode": "current",
  "blocks": [
    { "id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip",
      "start_month": 1, "end_month": 12 },
    { "id": "b2", "crop": "oats", "acres": 15, "irrigation": "sprinkler",
      "start_month": 11, "end_month": 4 },
    { "id": "b3", "crop": "corn", "acres": 15, "irrigation": "flood",
      "start_month": 5, "end_month": 9 }
  ],
  "optional": {
    "soil": "loam",
    "water_available_af": null,
    "water_applied_af": null,
    "surface_water_share": 0.5
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `location.lat` | number | yes | -90 to 90 |
| `location.lon` | number | yes | -180 to 180 |
| `location.label` | string | no | Display name, echoed back |
| `years` | `[start, end]` | yes | Inclusive. 1984 or later, start no later than end, and no later than last year |
| `price_mode` | `"current"` or `"historical"` | no, default `"current"` | `current` uses the latest price for every year. `historical` uses each year's own price |
| `blocks` | list | yes, at least 1 | Block ids must be unique |
| `blocks[].id` | string | yes | Short id such as `"b1"` |
| `blocks[].crop` | crop id | yes | See crop ids below |
| `blocks[].acres` | number | yes | Greater than 0 |
| `blocks[].irrigation` | `"drip"`, `"micro_sprinkler"`, `"sprinkler"`, `"flood"` | yes | |
| `blocks[].start_month` | 1 to 12 | yes | |
| `blocks[].end_month` | 1 to 12 | yes | Can be less than `start_month` (wraps) |
| `optional` | object | no | Every field inside it is optional |
| `optional.soil` | `"sand"`, `"loam"`, `"clay"` | no, default `"loam"` | |
| `optional.water_available_af` | number or null | no | Cap on total farm water per year. Split across blocks in proportion to need, and crops run short when it binds |
| `optional.water_applied_af` | number or null | no | What the farmer says they actually apply per year. Used for the `over_applied` waste flag |
| `optional.surface_water_share` | 0 to 1 | no, default 0.5 | Share of applied water from surface water. The rest is pumped groundwater |
| `optional.budget_usd` | number or null | no, default null | Yearly operating budget in dollars. `null` means no budget. Used for the `budget` check |
| `available_acres` | number | yes for new clients | Total land the farm has, greater than 0. If missing, it defaults to the sum of block acres so older clients still work. Used for the `land` check |

**Crop ids** (they match the `crop` column in `data/reference/prices/crop_prices.csv`):

| id | Display name | Perennial |
|---|---|---|
| `almonds` | Almonds | yes |
| `walnuts` | Walnuts | yes |
| `alfalfa_hay` | Alfalfa | yes |
| `processing_tomatoes` | Processing tomatoes | no |
| `corn` | Corn | no |
| `oats` | Oats | no |

**Planting windows** (`data/reference/crops.json`, read through `backend/reference.py`). Each annual has `planting_months`, the months (1 to 12) in which a Central Valley planting can start, and `season_days`, the days from planting to harvest. `season_days` is the sum of the crop's existing `stage_days`. Perennials have `planting_months: null` and are treated as year-round; they have no `season_days`. The planting months cite UC ANR or UC Davis publications and are all marked `verify: true` until checked against the text.

| id | `planting_months` | `season_days` |
|---|---|---|
| `processing_tomatoes` | 3, 4, 5 | 155 (35 + 40 + 50 + 30) |
| `corn` | 3, 4, 5, 6 | 150 (30 + 40 + 50 + 30) |
| `oats` | 10, 11, 12, 1 | 160 (20 + 50 + 60 + 30) |
| `almonds`, `walnuts`, `alfalfa_hay` | null (year-round) | none |

Processing tomato planting starts in March: February was removed because no checked UC source supports it.

**Frost check** (`backend/frost.py`). Each annual also has `frost_tolerant` (oats `true`, processing tomatoes and corn `false`; UC sources, `verify: true`). For a planting window at the farm's location, `frost_risk_share` is the share of backtest years where the NASA POWER daily minimum (`T2M_MIN`) is at or below 0 C on any of the first 45 days after planting (the 1st of the start month is day 1; a season that wraps the new year is planted in the year before the season year). Years whose 45 days are not all in the weather record are not counted. `/api/simulate` adds a neutral sentence to `assumptions` for each annual block whose window has `frost_risk_share` above 0.2, for example `"Frost occurred within 45 days of planting in 6 of 20 years for block b2 (corn planted in Mar)."` The optimizer leaves out options for crops that are not frost tolerant when the share is above 0.2 (see POST /api/optimize).

The simulation still stretches or shrinks `stage_days` to fit each block's start and end months; `season_days` does not change simulation results. Because the planting windows now exist, `POST /api/simulate` returns `planting_window` comparisons for annual entries (see System comparisons below).

Unknown fields are rejected. A bad request gets FastAPI's standard `422` response, with a `detail` list naming each bad field.

## Response

Shortened here. See [example_response.json](example_response.json) for all 25 years.

```json
{
  "location": { "label": "Merced, CA", "grid_cell": [37.5, -120.625],
                "county": "Merced", "cost_region": "San Joaquin Valley North" },
  "years": [2000, 2001, "...", 2024],
  "blocks": [
    { "id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip",
      "yearly": [
        { "year": 2000, "crop_water_use_in": 44.1, "effective_rain_in": 6.2,
          "irrigation_need_af": 126.3, "water_applied_af": 140.3,
          "relative_yield": 0.97, "heat_stress_days": 11, "gdd": 2890,
          "revenue": 210000, "cost": 165000, "profit": 45000 }
      ] }
  ],
  "farm_totals": [
    { "year": 2000, "water_applied_af": 260.4, "relative_yield": 0.95,
      "revenue": 300000, "cost": 240000, "profit": 60000 }
  ],
  "summary": { "best_year": 2005, "worst_year": 2015, "typical_year": 2010,
               "drought_years": [2014, 2015, 2021, 2022] },
  "waste_flags": [
    { "block_id": "b3", "type": "irrigation_method",
      "message": "Flood irrigation on corn loses about 28 acre-ft per year compared with drip.",
      "estimated_af_per_year": 28, "estimated_cost_per_year": 1400 }
  ],
  "assumptions": [
    "Mature, full-producing orchards.",
    "Weather is regional (NASA POWER grid cell about 50 km wide).",
    "Yield losses from weather and water only."
  ],
  "yield_weight": [
    { "block_id": "b3", "crop": "corn", "acres": 15, "source_unit": "BU / ACRE",
      "conversion": "bu x 56 lb / 2000",
      "yearly": [
        { "year": 2000, "tons_per_acre": 4.41, "tons": 66.15, "relative_yield": 0.95 }
      ],
      "avg_tons": 64.8, "avg_tons_per_acre": 4.32 }
  ],
  "summary_stats": { "years_count": 25, "avg_yield_tons": 182.4, "...": "see Part A" }
}
```

### `location`

| Field | Type | Notes |
|---|---|---|
| `label` | string | Echoed from the request |
| `grid_cell` | `[lat, lon]` | Center of the NASA POWER grid cell used for weather |
| `county` | string or null | From the location context. `null` outside California |
| `cost_region` | string or null | From the location context. `null` outside California |

### `blocks[].yearly[]`

One entry per season year, in the same order as `years`.

| Field | Type | Notes |
|---|---|---|
| `year` | int | Season year (see conventions) |
| `crop_water_use_in` | number | Full crop ET (ETc = Kc x ET0) for the season, inches |
| `effective_rain_in` | number | Rain the crop could use, inches |
| `irrigation_need_af` | number | Net irrigation need for the whole block, acre-ft |
| `water_applied_af` | number | Gross water applied (net / irrigation efficiency, capped by `water_available_af` if set), acre-ft |
| `relative_yield` | 0 to 1 | FAO-33 Ky method, plus a small cut for heat stress |
| `heat_stress_days` | int | Days above the crop's heat stress threshold in the season |
| `gdd` | number | Growing degree days over the season |
| `revenue` | number or null | (relative_yield / median relative_yield over this block's backtest) x baseline_yield x acres x price; same harvest basis as yield_weight |
| `cost` | number or null | Production cost excluding water, plus surface water cost, plus groundwater pumping cost |
| `profit` | number or null | revenue - cost |

### `farm_totals[]`

One entry per year. `water_applied_af` and money are sums over blocks. `relative_yield` is the acre-weighted mean of the block values. Money sums only the blocks whose money is not `null` (the left-out blocks are named in `assumptions`), and is `null` only when no block has money that year.

### `summary`

| Field | Type | Notes |
|---|---|---|
| `best_year` | int | Highest farm profit. Falls back to farm relative yield when any year's farm profit is `null`. The ranking used is stated in `assumptions` |
| `worst_year` | int | Lowest by the same ranking |
| `typical_year` | int | Median year by the same ranking |
| `drought_years` | int list | Known California drought years (2014, 2015, 2021, 2022) that fall in the requested range. Can be empty |

### `yield_weight[]`

Harvest weight per block, one entry per block in request order. Added in iteration 2 (Part C). Built in `backend/yield_weight.py`.

| Field | Type | Notes |
|---|---|---|
| `block_id` | string | Same as `blocks[].id` |
| `crop` | crop id | |
| `acres` | number | |
| `source_unit` | string or null | Unit of the NASS baseline yield, such as `"BU / ACRE"`. `null` when the crop has no baseline yield |
| `conversion` | string or null | Short text such as `"lb / 2000"`, `"bu x 56 lb / 2000"`, or `"already tons"`. `null` when there is no weight |
| `yearly[].year` | int | Same order as `years` |
| `yearly[].tons_per_acre` | number or null | US tons per acre (see the formula below) |
| `yearly[].tons` | number or null | `tons_per_acre` x `acres` |
| `yearly[].relative_yield` | 0 to 1 | Same value as `blocks[].yearly[].relative_yield` |
| `avg_tons` | number or null | Mean of `yearly[].tons` |
| `avg_tons_per_acre` | number or null | Mean of `yearly[].tons_per_acre` |

**Formula.** The baseline yield from the location context is converted to tons per acre (`backend/units.py`: `LB / ACRE` divided by 2000, `BU / ACRE` times the crop's bushel weight (corn 56 lb, oats 32 lb, wheat 60 lb) divided by 2000, `TONS / ACRE` unchanged). The county median yield already reflects a typical year, not a perfect one, so each year is scaled against the block's median relative yield over all backtest years:

```
tons_per_acre = baseline_tons_per_acre x relative_yield / median(relative_yield of this block)
```

A typical year shows the typical county harvest, drought years show less, and good years show a bit more. The weights are `null` when the crop has no baseline yield, its unit cannot be converted, or the median relative yield is 0. A note goes into `assumptions` in each case.

Other code (scenario comparisons, the optimizer) should call `tons_per_acre_by_year(crop, location, relative_yields)` in `backend/yield_weight.py` so every part of the app uses the same conversion.

### `waste_flags[]`

Sorted by `estimated_af_per_year`, largest first. Can be an empty list.

| Field | Type | Notes |
|---|---|---|
| `block_id` | string | Which block. `"farm"` for the farm-wide `over_applied` flag |
| `type` | string | One of the four types below |
| `message` | string | Plain English. Show it to the farmer as is |
| `estimated_af_per_year` | number | Average water that could be saved per year |
| `estimated_cost_per_year` | number or null | Dollars per year, using the location's water prices. `null` if no water price is known |

| `type` | When it fires |
|---|---|
| `irrigation_method` | The block's irrigation method loses more water than drip would for the same crop |
| `over_applied` | `optional.water_applied_af` is set and more than 5 percent above the modeled gross need for the whole farm. `block_id` is `"farm"` |
| `rain_covered` | Water was applied in weeks where rain already covered the crop's needs |
| `low_holding_soil` | A high water use crop is on sand |

### `assumptions`

A list of plain English strings, worded as facts with no advice (a test scans every string the API can return for advice phrases). Includes the fixed model assumptions, the ranking used in `summary`, the price mode, and every `data_quality` note from the location context. Show all of them in the "Why this result?" panel.

### Iteration 2 additions (Part A)

Built by `backend/summary.py`. An older backend leaves these out, so the UI should handle them missing. Any value that cannot be computed is `null`, never 0. Part A's original `production` field was replaced by `yield_weight` (see above), so harvest amounts are always US tons.

```json
"summary_stats": { "years_count": 20, "total_profit": 1194836, "avg_profit": 59742,
                   "avg_relative_yield": 0.983, "avg_water_applied_af": 226.8, "avg_cost": 150520,
                   "avg_yield_tons": 182.4 },
"budget": { "budget_usd": 160000, "years_over_budget": [], "max_overrun_usd": null },
"land": { "available_acres": 60, "peak_acres_in_use": 55, "peak_month": "Jan",
          "over_capacity_months": [] }
```

**`summary_stats`**

| Field | Type | Notes |
|---|---|---|
| `years_count` | int | Number of backtest years |
| `total_profit` | number or null | Sum of `farm_totals[].profit` over years that have it |
| `avg_profit` | number or null | Mean of the same years |
| `avg_relative_yield` | number or null | Mean of the yearly area-weighted farm values |
| `avg_water_applied_af` | number or null | Mean yearly farm water applied |
| `avg_cost` | number or null | Mean of `farm_totals[].cost` over years that have it |
| `avg_yield_tons` | number or null | Average over years of the farm's total harvest weight in US tons, from `yield_weight`. Each year adds up the blocks that have a weight (left-out blocks are named in `assumptions`). `null` when no block has a weight |

When some years have no profit, the profit fields use only the years that do, and `assumptions` says how many.

**`budget`**

| Field | Type | Notes |
|---|---|---|
| `budget_usd` | number or null | Echoes `optional.budget_usd` |
| `years_over_budget` | int list | Years where farm cost was above the budget. Empty when there is no budget |
| `max_overrun_usd` | number or null | The largest cost minus budget. `null` when no year is over |

Farm cost only includes blocks with price data. If a block has no production cost, `assumptions` notes that the real total may be higher.

**`land`**

| Field | Type | Notes |
|---|---|---|
| `available_acres` | number | From the request, or the sum of block acres |
| `peak_acres_in_use` | number | The most acres in the ground in any one month |
| `peak_month` | string | `"Jan"` to `"Dec"`, the first month that reaches the peak |
| `over_capacity_months` | string list | Months where acres in the ground exceed `available_acres` |

For each month, the acres of every block growing that month are added up (Nov to Apr wraps the new year). A winter crop and a summer crop on the same acres never overlap. Over-capacity months add an `assumptions` note, and the backtest still runs as entered.

## GET /api/meta

The backtest year range and the period presets that fit inside it. No request body.

```json
{ "first_year": 1985, "last_full_year": 2025, "presets": [5, 10, 20, 30, 40] }
```

`first_year` is 1985: NASA POWER data starts in 1984, and a season that wraps the new year needs the previous year. `last_full_year` is December 31 of last year. Presets longer than the available history are dropped.

## POST /api/compare

Runs 2 to 6 saved setups through the same engine and ranks them.

```json
{
  "configs": [
    { "name": "Today", "farm": { "...same shape as a /api/simulate request..." } },
    { "name": "All drip", "farm": { "..." } }
  ],
  "ranked_by": "avg_profit"
}
```

| Field | Type | Notes |
|---|---|---|
| `configs` | list of `{name, farm}` | 2 to 6 setups. Names must be unique. `farm` is a full `/api/simulate` request |
| `ranked_by` | string | `"avg_profit"` (default), `"total_profit"`, `"avg_relative_yield"`, or `"avg_water_applied_af"`. Higher is first, except water, where lower is first |

Response:

```json
{
  "results": [
    { "name": "All drip", "summary_stats": { "..." }, "budget": { "..." }, "rank": 1 },
    { "name": "Today", "summary_stats": { "..." }, "budget": { "..." }, "rank": 2 }
  ],
  "ranked_by": "avg_profit"
}
```

Results come back in rank order. Equal values share a rank (1, 2, 2, 4), and a setup with a `null` ranking value ranks after every setup that has one. A wrong number of setups, a repeated name, or an unknown `ranked_by` gets a `422` with a clear message.

## Location context

The engine gets baseline yields, production costs, and the surface water price only from `get_location_context(lat, lon)` in `backend/regions.py`, never from hardcoded Merced values. Marco owns and builds that function. Until it is merged, `backend/simulate.py` uses a private Merced-only fallback with the same shape and adds the note "Using Merced defaults until the California data layer is merged."

The Pydantic model `LocationContext` in `backend/schemas.py` describes this shape.

```json
{
  "state": "CA",
  "county": "Merced",
  "in_california": true,
  "cost_region": "San Joaquin Valley North",
  "baseline_yields": {
    "almonds": { "value": 2400, "unit": "LB / ACRE", "basis": "county",
                 "source": "NASS county median, 1984-2024" }
  },
  "production_costs": {
    "almonds": { "cost_excl_water": 4200, "unit": "$ / ACRE",
                 "region": "San Joaquin Valley North",
                 "source": "UC Davis cost study 2023, p. 12" }
  },
  "surface_water_price_per_af": 50,
  "data_quality": [
    "Walnut yield uses statewide average (no county data for Merced)."
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `state` | string or null | Two-letter state code. `null` outside the US |
| `county` | string or null | |
| `in_california` | bool | |
| `cost_region` | string or null | UC Davis cost study region |
| `baseline_yields` | map of crop id to object | `value`, `unit` (NASS style, such as `"LB / ACRE"` or `"TONS / ACRE"`), `basis` (`"county"` or `"state"` for a statewide fallback), `source` |
| `production_costs` | map of crop id to object | `cost_excl_water`, `unit` (`"$ / ACRE"`), `region`, `source` |
| `surface_water_price_per_af` | number or null | Dollars per acre-ft |
| `data_quality` | string list | Notes the engine copies into the response `assumptions` |

A crop can be missing from `baseline_yields` or `production_costs` when no data exists anywhere. The engine then still returns water and relative yield for that crop, sets its revenue, cost, and profit to `null`, and adds a note to `assumptions`. The numbers above only show the shape.

## System comparisons (Part B, iteration 2)

The response now includes `comparisons` (an empty list when no alternatives can be evaluated). Existing fields remain unchanged. Each item has:

```json
{
  "block_id": "b3",
  "crop": "corn",
  "kind": "irrigation",
  "current": {"irrigation": "flood", "start_month": 5, "end_month": 9},
  "alternative": {"irrigation": "drip", "start_month": 5, "end_month": 9},
  "avg_profit_change": 1189,
  "avg_relative_yield_change_pts": 0.4,
  "avg_water_change_af": -20.5,
  "worst_year_profit_change": 2100,
  "excludes": "Installation cost of the new system is not included."
}
```

Numbers above illustrate the shape; they are not measured results.

- Each alternative changes exactly one entry, retaining its acres, crop, location, years, price mode, and optional inputs. With a water cap, the whole farm is simulated using the existing engine and the same weather/context, with nested comparisons disabled. Without a cap, entries are independent, so only the changed entry is simulated at its actual acreage; tests confirm it matches a full-farm rerun.
- Metrics describe the **changed crop entry**, not total farm differences. Farm water allocation is recalculated, so other entries can also change under a water cap; the exclusion note explicitly flags this. Profit and water changes are alternative minus current. Relative yield change is in **percentage points**, not harvested weight. Worst-year change is the alternative's minimum profit minus the current minimum; these minima may occur in different years.
- Financial differences are null unless profit is available for that entry in both setups in every compared year. Null means unavailable, never zero. The UI can display `No price data`.
- Within each block, rows are ordered by average profit change descending, with nulls last. This is ordering, not advice or a suitability ranking.
- Irrigation alternatives include each other API irrigation type. Installation costs are excluded.
- Annual planting alternatives use only `planting_months` already present in crop reference data, accepting either a list or the existing `{value, source, verify}` format. The end month shifts by the same number of months, wrapping December. No dates are invented when the list is missing. Perennials get no planting-window comparisons. Market timing and field operations are excluded.
- Alternatives requiring weather outside the available record are omitted, with an explanation in `assumptions`.
- Budget checks are not added by this feature. The current engine does not yet accept Part A's yearly budget field; once added, comparison requests preserve it along with the other farm inputs.
- Internal callers such as the optimizer can use `simulate(..., include_comparisons=False)` to avoid generating nested alternatives. The public endpoint includes comparisons by default.
- No new endpoint is needed: `POST /api/simulate` includes the comparisons. This change does not alter the frontend or add absolute harvest quantities (those are in `yield_weight`).

## POST /api/optimize (Part C, iteration 2)

Finds the crop plan that scores highest on one objective within the farm's land, budget, and water. Logic is in `backend/optimize.py`; models are `OptimizeRequest` and `OptimizeResponse` in `backend/schemas.py`.

### Request

```json
{
  "location": { "lat": 37.30, "lon": -120.48, "label": "Merced, CA" },
  "years": [2005, 2024],
  "price_mode": "current",
  "available_acres": 160,
  "budget_usd": 400000,
  "budget_rule": "every_year",
  "water_available_af": 450,
  "objective": "profit",
  "allowed_crops": null,
  "allowed_irrigation": null,
  "allow_new_perennials": false,
  "max_share_per_crop": 0.7,
  "min_block_acres": 5,
  "soil": "loam",
  "current_farm": { "blocks": [
    { "id": "b1", "crop": "almonds", "acres": 80, "irrigation": "micro_sprinkler",
      "start_month": 1, "end_month": 12 },
    { "id": "b3", "crop": "corn", "acres": 60, "irrigation": "flood",
      "start_month": 5, "end_month": 9 }
  ] }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `location`, `years`, `price_mode` | | same as `/api/simulate` | |
| `available_acres` | number > 0 | yes | Land the plan can use in any one month |
| `budget_usd` | number >= 0 | yes | Yearly operating budget in dollars |
| `budget_rule` | `"every_year"` or `"average"` | no, default `"every_year"` | `every_year`: farm cost at or under the budget in every backtest year. `average`: average yearly cost at or under the budget; single years can go over |
| `water_available_af` | number or null | no | Farm water limit per year, acre-ft. The plan's full irrigation must fit under it in every year |
| `objective` | `"profit"`, `"production_value"`, `"profit_per_af"` | no, default `"profit"` | Average yearly profit; average yearly revenue at current prices (whatever `price_mode` is, so crops are compared by value, never by raw tons); or average profit divided by average water applied |
| `allowed_crops` | crop id list or null | no, default all | At least one when given |
| `allowed_irrigation` | irrigation list or null | no, default all | At least one when given |
| `allow_new_perennials` | bool | no, default false | When false, each perennial (almonds, walnuts, alfalfa) keeps exactly its `current_farm` acres (rounded to 0.1 acre); its irrigation type can change. Perennials the current farm does not grow are not planted |
| `max_share_per_crop` | number, 0 < x <= 1 | no, default 0.7 | Each crop's acres (all its blocks) at most this share of `available_acres` |
| `min_block_acres` | number >= 0 | no, default 5 | Each block in the plan is at least this big |
| `soil` | `"sand"`, `"loam"`, `"clay"` | no, default `"loam"` | |
| `current_farm` | `{blocks}` or null | no | The farm today, same block shape as `/api/simulate`. It sets the locked perennial acres and is evaluated with the request's location, years, price mode, soil, budget, and water limit |

Surface water share uses the `/api/simulate` default (0.5). Unknown fields, a missing `available_acres` or `budget_usd`, and out of range values get a `422`.

### Response

```json
{
  "status": "optimal",
  "objective": "profit",
  "plan": {
    "blocks": [
      { "id": "p1", "crop": "almonds", "acres": 80.0, "irrigation": "drip",
        "start_month": 1, "end_month": 12, "avg_profit": 134626, "avg_yield_tons": 77.59 },
      { "id": "p2", "crop": "processing_tomatoes", "acres": 39.3, "irrigation": "drip",
        "start_month": 2, "end_month": 6, "avg_profit": 105626, "avg_yield_tons": 1874.55 }
    ],
    "summary_stats": { "years_count": 20, "avg_profit": 240251, "avg_yield_tons": 1952.14, "...": "..." },
    "budget": { "budget_usd": 400000, "years_over_budget": [], "max_overrun_usd": null },
    "land": { "available_acres": 160, "peak_acres_in_use": 119.3, "peak_month": "Feb",
              "over_capacity_months": [] }
  },
  "current_farm": { "blocks": ["..."], "summary_stats": { "...": "..." }, "budget": { "...": "..." } },
  "difference_vs_current": { "avg_profit": 169933, "avg_yield_tons": 1548.51,
                             "avg_water_applied_af": -72.4, "avg_cost": 45797 },
  "alternatives": [
    { "label": "Alternative 1", "blocks": ["..."], "summary_stats": { "...": "..." },
      "budget": { "...": "..." } }
  ],
  "binding_constraints": [
    "Water limit is reached in 2021.",
    "Almonds acres are fixed at the current 80 acres because new perennial plantings are off."
  ],
  "infeasible_reason": null,
  "error_detail": null,
  "options_considered": 36,
  "assumptions": ["..."]
}
```

Numbers above are from one run on cached Merced weather and show the shape only.

| Field | Type | Notes |
|---|---|---|
| `status` | `"optimal"`, `"feasible"`, `"no_profitable_plan"`, `"infeasible"`, `"error"` | `optimal`: the solver proved the plan highest scoring for the model. `feasible`: highest found within the 20 second solver limit. `no_profitable_plan`: blocks fit, but none makes money (or adds value), so the highest scoring plan is unplanted land. `infeasible`: the limits cannot all be met; see `infeasible_reason`. `error`: the plan failed the engine check; see `error_detail`. No plan is returned in that case |
| `objective` | string | Echoes the request |
| `plan` | object or null | Only for `optimal` and `feasible`. `blocks` are `/api/simulate` request blocks (ids `p1`, `p2`, ...) plus `avg_profit` and `avg_yield_tons` for that block; drop those two fields before posting the blocks to `/api/simulate`. `summary_stats`, `budget`, and `land` have the Part A shapes and come from running the blocks through `/api/simulate` with the request's budget, water limit, and available acres. `summary_stats.avg_yield_tons` is always filled when the crops have baseline yields |
| `current_farm` | object or null | `null` without a `current_farm`. Blocks carry the same `avg_profit` and `avg_yield_tons`; `summary_stats` and `budget` come from the same engine and settings |
| `difference_vs_current` | object or null | Plan minus current farm. A field is `null` when either side is `null`. `null` when there is no plan or no current farm |
| `alternatives` | list | Up to 3 more plans, labeled `"Alternative 1"` to `"Alternative 3"`, each found by solving again with a no-good cut that forbids every option set already used, and each checked by the engine. A plan whose engine results equal the main plan's or an earlier alternative's is skipped (up to 12 solves) |
| `binding_constraints` | string list | Plain sentences for limits with no room left: no block in the plan could grow by 0.1 acre without breaking it. Examples: `"Land is fully used May to Sep."`, `"Budget is the limit in 2015 and 2022."`, `"Water limit is reached in 2021."`, crop share limits, locked perennial acres, blocks at the minimum size |
| `infeasible_reason` | string or null | Plain English, for `infeasible` and `no_profitable_plan`. Examples: `"The locked almond acres cost more than the budget in 2022."`, `"Even a 5 acre block of the cheapest option (oat, drip, Oct to Feb) costs $1,250 in its costliest year, more than the $100 budget."` |
| `error_detail` | string or null | What failed in the engine check, for `error` |
| `options_considered` | int | Options with complete money data that entered the search. `assumptions` says why any other option was left out |
| `assumptions` | string list | Optimizer notes first, then the plan's `/api/simulate` assumptions. Text fields describe results only; none give advice |

### How the plan is found

1. **Options.** Every allowed (crop, irrigation, start month). Options for crops that are not frost tolerant are left out when `frost_risk_share` for their window is above 0.2 (see Frost check above); `assumptions` says how many options were left out and lists each window with its frost years, for example `"4 options were left out because frost occurred within 45 days of planting in more than 20% of the backtest years and the crop is not frost tolerant: processing tomato planted in Feb (11 of 20 years)."` Perennials: one option per irrigation type, year-round (1 to 12). Annuals: every month in `planting_months` (see Planting windows above), lasting `round(season_days / 30.44)` whole months from the 1st of that month, wrapping past December (5 months for each annual today: corn planted in May runs 5 to 9, oats planted in October run 10 to 2). Annuals without `planting_months` are skipped.
2. **Per acre results.** Each option runs through the existing engine (`run_backtest` and `apply_money`, the code behind `/api/simulate`) for exactly 1 acre with no farm water limit. Per year: water applied, relative yield, US tons per acre (`backend/units.py`, scaled the same way as `yield_weight`), revenue, revenue at current prices, and total cost including water with the `/api/simulate` surface and groundwater split; plus the months occupied. Results are cached per option and input set. There is no second water or yield model: without a water limit the engine is linear in acres.
3. **Mixed integer program** (scipy `milp`, HiGHS). Acres are whole multiples of 0.1, so the solver's answer is used as is. A binary per option gives `min_block_acres <= acres <= available_acres` or 0. Constraints: land per calendar month (a winter crop and a summer crop can share acres), budget per year or on average, water per year, crop share, and locked perennial acres. Profit per acre-foot is solved exactly with Dinkelbach iterations, then the most profit at that ratio; if a profitable plan needs no irrigation water, its ratio has no upper limit and `assumptions` says so. Ties prefer less water. The budget used by the solver is lowered by half a dollar per option plus one dollar, so the engine's whole dollar rounding cannot push a year over.
4. **Verify.** The blocks run through the full `simulate` path. Average profit, cost, and water must match the optimizer within 1 percent (or the engine's rounding: one dollar per block plus one, 0.15 acre-ft), and no land, budget, water, crop share, or locked acre limit may be broken in any year. The engine must not have had to share out water. Any failure returns `status: "error"` instead of a plan.
5. **Not included.** Installation cost for a new irrigation system and orchard establishment: new orchards take 3 to 5 years to bear, and establishment costs are not modeled. Frost does not lower modeled yields; it is used only to leave out frost sensitive planting windows (see Frost check).
6. **Errors.** A `current_farm` season outside the weather record gets a `422`, like `/api/simulate`. Data service failures get a `502`.


## Calculation details and financial interpretation

Public `POST /api/simulate` responses include optional `calculation_details`. Old responses can omit it; the UI then reports that exact provenance is unavailable rather than inventing it. Model-internal calls with `include_comparisons=False` omit the audit payload.

The payload contains the model/data commit, financial coverage and exclusions, annual totals, period revenue/cost/margin reconciliation, and a block/year trace with season dates, acreage, baseline yield and its median source years, the exact crop and electricity price years selected, regional study inputs, pump/water assumptions, and unrounded calculation intermediates. Source entries link to the immutable input extracts and embed matching records. Each weather link recreates the POWER request for the snapped coordinates, season dates, and parameters. Upstream POWER revisions can change a later replay; the link alone is not a byte-for-byte archive.

**Revenue alignment change:** revenue now values the same median-normalized harvest as `yield_weight`, using rounded relative yields (as the harvest module does). The previous revenue formula omitted the median denominator and could disagree with the harvest displayed. This changes financial outputs and optimizer objectives. Dollars remain rounded to whole units in ordinary result rows; audit intermediates remain unrounded. A zero median yields unavailable harvest and financial outputs.

**Costs are estimates, not farmer expenses.** They use the context-selected regional cost study excluding water, multiplied by acreage, plus modeled water cost. The study is held fixed across weather years, with no inflation adjustment. `optional.budget_usd` is a budget constraint/check, never an expense observation or a replacement for production cost. No actual-cost override was added here.

Dollar totals still include only entries with all required financial inputs. Harvest/water totals can have broader coverage; `excluded_financial_blocks` makes that explicit. These dollar values are modeled margins on priced crops, not verified net farm income. The audit surfaces conflicting cost study year versus PDF-filename metadata as provisional instead of claiming it was verified. Tracing sources is separate from validating predictive accuracy.
