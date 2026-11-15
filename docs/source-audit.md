# Backtest source and input audit

Scope: default Merced almonds/oats/corn example and the numerical data flow used by all farm inputs. This is a source/calculation audit, not validation against observed farm harvests.

## What is actually in GitHub

The main tree has extracted CSV/JSON files and extraction scripts, but no committed PDFs. The original data/raw folder is ignored. Two publisher PDFs were reacquired, their covers and relevant cost tables read, and the cost pages visually checked. SHA-256, URL, table/page, year and verified category totals are recorded in data/reference/prices/cost_study_audit.json. The downloaded originals remain uncommitted in data/raw/source_audit. The existing extract_production_costs.extract_pdf function was rerun on both and reproduced the committed operating/water/non-water amounts and cover years without extraction warnings.

## Verified cost inputs

| Source | Operating cost/acre | Study water/acre | Non-water/acre used by model | Source location |
|---|---:|---:|---:|---|
| UC Sacramento almonds, 2024 | 3,720 | 637 | 3,083 | Table 3, PDF page 19 |
| UC Sacramento/Northern San Joaquin field corn, 2015 | 1,118 | 168 | 950 | Table 2, PDF page 11 |

The almond filename in the old extract contains 2022, but the publisher PDF cover/table say 2024. Its numerical operating-cost extract matches the 2024 PDF; the audited source registry resolves that legacy-label mismatch. Other crop-study sources have not been independently checked in this audit and must not be presented as verified.

PDFs: https://www.almonds.org/sites/default/files/2025-05/2024SacValleyAlmonds7.5.24.%20Final%20draft.pdf#page=19 and https://coststudyfiles.ucdavis.edu/uploads/cs_public/03/dc/03dc4496-32af-47c6-b479-38e1d27c134e/15cornsacramentovalleyfinaldraftjuly20.pdf#page=11

Both studies round printed category totals. Their printed non-water categories sum to one dollar more per acre than the published operating total minus water. An explicit -1 dollar/acre printed-table rounding entry reconciles them. It is not a claimed expense credit.

The study water-purchase/pumping amount is removed before the model adds surface-water charges and pumping-energy cost. Irrigation labor, services and non-water additives stay in the non-water study amount. This avoids counting the source water charge twice.

## Corrected calculation defect

Previously, harvest was calibrated by the median relative yield inside each submitted scenario. A synthetic regression case with 10 acres of corn returned about 44.8 tons with unlimited water, a 20 acre-ft cap, and a 10 acre-ft cap, although modeled relative yield fell from 1.0 to about 0.646 and 0.364. Recalibrating to the reduced median canceled the water-loss signal.

The backtest now saves the median relative yield from its uncapped-water run for each crop/calendar/soil/window and reuses that reference for capped harvest and revenue. The model already computes this uncapped run to allocate farm water; it is not a second yield model. Harvest and sales use the same fixed denominator. After correction, the same synthetic case produced 44.8 tons with uncapped water, about 28.94 tons at 20 acre-ft and 16.31 tons at 10 acre-ft; annual sales fell from $7,520 to about $4,858 and $2,737. These are regression fixtures, not real farm forecasts. Regression tests require lower modeled harvest and sales when water is reduced. This corrects numerical consistency but does not establish agronomic calibration accuracy.

## Farm-input mapping

- Location -> weather grid and county/state yield reference; regional cost study with explicit fallback.
- Crop and growing months -> coefficient/stage curve, heat/GDD dates, seasonal weather; wrap counted in ending year.
- Acres -> harvest, non-water study costs, irrigation volumes, monthly land occupancy.
- Irrigation -> application efficiency and gross applied water; a study's non-water equipment/labor costs are not separately repriced for each irrigation method.
- Water cap -> full-farm allocation and ETa/yield response; the harvest reference is kept uncapped.
- Soil -> water-holding balance. Initial full soil storage remains a model assumption.
- Price mode -> latest stored or historical/nearest crop and electricity price, with actual source year exposed.
- Budget -> comparison constraint/check, not actual farm operating expenses.

## Interpretation and unresolved limits

These are margins above modeled operating costs, not net income. Separate cash/non-cash overhead, establishment, and the farmer's actual accounts are not included. Non-water study costs are fixed per acre, not inflation adjusted or dynamically repriced for harvest-dependent hulling, rent or financing. The PDF tables use study-specific yield/price assumptions; the app instead uses NASS baseline yields, model weather response, and selected NASS prices, so it is not expected to reproduce the study's total returns unchanged.

Yield-reference extracts can include years after the chosen weather window. Current-price mode and these reference medians make this a retrospective scenario, not an out-of-sample historical forecast. Oats financial totals remain unavailable because no production-cost study is present. Harvest/water can include crops excluded from money totals.

Several coefficients remain explicitly marked verify=true in crops.json, irrigation.json and soils.json, including orchard Ky proxies and heat/GDD assumptions. The heat penalty is a team rule. These must not be called empirically validated predictions just because the arithmetic reconciles. No new evidence supports removing those flags.

## Verification

Tests cover harvest and revenue consistency, water-limit monotonicity with a fixed reference, expense sums and unit conversions, source years/season URLs, missing data and PDF-category reconciliation. The UI gives a one-line calculation for the selected metric and distinguishes weather inputs, repo references and model outputs. Full precision remains downloadable. Actual predictive accuracy still requires independent observed yield data and held-out-year validation.
