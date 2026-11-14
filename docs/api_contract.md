# Simulate API contract

`POST /api/simulate` runs the backtest for one farm and returns yearly water use, relative yield, and money per block, plus farm totals, a summary, and waste flags.

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
  ]
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
| `revenue` | number or null | relative_yield x baseline_yield x acres x price |
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

A list of plain English strings. Includes the fixed model assumptions, the ranking used in `summary`, the price mode, and every `data_quality` note from the location context. Show all of them in the "Why this result?" panel.

### Iteration 2 additions (Part A)

Built by `backend/summary.py`. An older backend leaves these out, so the UI should handle them missing. Any value that cannot be computed is `null`, never 0.

```json
"summary_stats": { "years_count": 20, "total_profit": 1194836, "avg_profit": 59742,
                   "avg_relative_yield": 0.983, "avg_water_applied_af": 226.8, "avg_cost": 150520 },
"budget": { "budget_usd": 160000, "years_over_budget": [], "max_overrun_usd": null },
"land": { "available_acres": 60, "peak_acres_in_use": 55, "peak_month": "Jan",
          "over_capacity_months": [] },
"production": [
  { "block_id": "b1", "crop": "almonds", "unit": "LB",
    "yearly": [ { "year": 2005, "value": 78400 } ] }
]
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

**`production[]`**

One entry per block, in farm order.

| Field | Type | Notes |
|---|---|---|
| `block_id`, `crop` | string | |
| `unit` | string or null | The baseline yield unit without `"/ ACRE"`, for example `"LB"`, `"TONS"`, or `"BU"`. `null` when the crop has no baseline yield |
| `yearly[]` | `{year, value}` | `value` = relative_yield x baseline yield x acres, from `get_location_context`. `null` when there is no baseline yield |

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
- No new endpoint is needed: `POST /api/simulate` includes the comparisons. This change does not alter the frontend or add absolute production quantities.
