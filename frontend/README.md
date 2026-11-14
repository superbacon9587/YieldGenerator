# YieldGenerator frontend

Person B's React + Vite + Recharts interface. All frontend work lives here. Backend and root files are owned by other teammates.

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open the URL Vite prints. It may select another port if 5173 is already occupied. Use `npm run build` for a production build and `npm test` for contract/form/scenario checks.

## Demo and backend modes

Live backend mode is the default. Demo remains available for offline walkthroughs. The top-right selector switches modes and clears old results. Demo search supports Merced, Fresno, Sacramento, Nairobi, New Delhi, and Sao Paulo; coordinates are always editable. Demo outputs are synthetic, including deliberately constructed drought dips and scenario effects. They are not NASA-derived, calibrated, or validated. Changing location in demo does not change the synthetic climate.

Backend mode calls `GET /api/geocode?q=...` and `POST /api/simulate`. Vite proxies `/api` to `http://127.0.0.1:8000`. Start the backend in a separate PowerShell window from the repository folder: `python -m uvicorn backend.api:app --reload`. The UI reports connection, timeout, validation, and malformed response errors; it never silently substitutes demo data for a failing real request.

To opt into offline demo mode at startup, put `VITE_USE_MOCK=true` in `frontend/.env.local`, then restart Vite. Otherwise leave the flag unset or set it to `false`. No private API keys belong in Vite variables or browser code. The example environment file contains only the mode flag.

## What is implemented

- Farm setup with location search or coordinates; editable crop entries; acreage or square-foot entry; irrigation and month controls; year and price modes; optional water/soil inputs; local persistence and reset.
- Live 12-month calendar supporting cross-year seasons.
- Yield-first results with water, yield, and profit chart tabs, backend-flagged years, selected-year crop table, assumptions, potential-loss flags, print, and JSON export.
- Frozen baseline and independent what-if requests. Custom crop/area/irrigation comparison, all-drip comparison, and water budget at 75% of baseline mean modeled applied water.
- Null money is shown as unavailable. Relative yield is explicitly a fraction of unstressed baseline, not harvested tonnes or pounds. Farm financial totals may be partial; the backend assumptions must explain missing crops.
- Suggestions initiate comparisons. They are not ranked agronomic recommendations. No absolute harvest quantity is invented when the API does not supply baseline yield and units.

## Contract

Implemented against `origin/feature/backtest:docs/api_contract.md`, inspected November 14, 2026. This includes `alfalfa_hay`, `micro_sprinkler`, null finances, and season-year wraparound semantics. Request fields: location, years, price_mode, blocks, optional. Example response: `src/mock/simulate_response.json`. Synthetic response generation: `src/mock/generate.js`.

Backend integration needs an end-to-end pass once the backtest and location-context branches are merged. Existing API routes in the local base do not include `/api/simulate` yet. Global location entry does not establish global crop, yield, or price validation.

## Frontend map

- `src/App.jsx`: shell, saved inputs, mode, API request, baseline snapshot.
- `src/components/FarmForm.jsx`: farm inputs.
- `src/components/Timeline.jsx`: month calendar.
- `src/components/Results.jsx`: charts, details, scenarios, export.
- `src/api.js`: demo and real transport.
- `src/domain.js`: request shape, validation, unit conversion, summaries, immutable scenarios.
- `src/styles.css`: responsive and print styling.

## Before a demo

Run `npm test` and `npm run build`. Enter the example farm, run a demo, inspect each chart, change the selected year, and compare a water cut. Test empty flags and missing money with backend fixtures. Use narrow/mobile and desktop layouts. Keep the demo banner visible in screenshots or recordings of synthetic results.

## Windows: run both servers

In the first PowerShell window, from your repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --reload
```

Skip environment creation if `.venv` already exists. These commands use the environment directly, so PowerShell script activation is optional.

In a second PowerShell window, from the same repository folder:

```powershell
cd frontend
npm ci
npm run dev
```

Keep both windows open. Select Live backend, run the default Merced farm, and check county, cost region, crop-by-crop results, and assumptions. The first real run may take longer while NASA weather is downloaded and cached. A historical backtest is a model of past conditions, not a guaranteed future harvest.

## What-if comparisons

Use What if things were different on Results to edit a crop entry's crop, acreage, irrigation, or annual growing months, then click Compare scenario. The quick water-limit and all-drip comparisons remain available. Each scenario uses the same historical years and leaves the original farm unchanged. There is no separate System comparisons section.
