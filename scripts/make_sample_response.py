"""Write the fixed sample /api/simulate response used by the chart and table tests.

    python3 scripts/make_sample_response.py

Real Merced reference data (NASS yields, UC Davis costs, prices, water rates) and the
synthetic Central Valley weather from tests/conftest.py, so the file needs no network.
Both tests/test_cross_checks.py and frontend/src/features/provenance/chartData.test.js
read it, so the backend and the browser are checked against the same numbers.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from conftest import make_weather  # noqa: E402
from backend import regions, simulate as engine  # noqa: E402
from backend.schemas import SimulateRequest  # noqa: E402

OUT = ROOT / "frontend/src/features/provenance/sample_response.json"
REQUEST = {
    "location": {"lat": 37.3, "lon": -120.48, "label": "Merced, California"},
    "years": [2012, 2016],
    "price_mode": "historical",
    "blocks": [
        {"id": "b1", "crop": "almonds", "acres": 40, "irrigation": "drip", "start_month": 1, "end_month": 12},
        {"id": "b2", "crop": "processing_tomatoes", "acres": 80.5, "irrigation": "drip", "start_month": 4, "end_month": 9},
        {"id": "b3", "crop": "corn", "acres": 15, "irrigation": "flood", "start_month": 5, "end_month": 9},
        {"id": "b4", "crop": "oats", "acres": 12, "irrigation": "flood", "start_month": 11, "end_month": 4},
    ],
    "optional": {"soil": "loam", "surface_water_share": 0.35, "budget_usd": 450000},
}


def sample():
    req = SimulateRequest.model_validate(REQUEST)
    ctx = regions.build_context({"state": "CA", "county": "Merced", "in_california": True})
    return engine.simulate(req, wx=make_weather("2010-01-01", "2017-12-31"), context=ctx)


if __name__ == "__main__":
    data = json.loads(sample().model_dump_json())
    # Keep what the chart and table tests read; the rest only makes the fixture large.
    data.pop("comparisons")
    data.pop("calculation_details")
    data["calculations"] = {k: v for k, v in data["calculations"].items()
                            if k.startswith(("summary.", "table.")) or k.endswith((".profit", ".cost"))}
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1000} KB)")
