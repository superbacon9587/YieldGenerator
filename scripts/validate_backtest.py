"""Compare modeled relative yield with real Merced County yields.

Run from the project root:
    python scripts/validate_backtest.py

For Merced, CA (lat 37.30, lon -120.48) this runs the backtest engine for 1 acre
of each crop that has Merced County yield data, over every year with data and
weather, and compares:
    modeled   relative_yield from backend/simulate.py (full irrigation, loam)
    actual    NASS yield / that crop's median Merced yield (the yield anomaly)

Yield data:
    data/validation/merced_yields.csv     corn and oats (the validation file)
    data/validation/ca_county_yields.csv  Merced rows for crops not in the file
                                          above (processing tomatoes), which is
                                          the only Merced series covering the
                                          2014, 2015, 2021, and 2022 droughts

Outputs:
    a table of correlation per crop and years compared (printed)
    docs/validation.png, modeled vs actual over time with drought years shaded

NASS yields also climb over time from better varieties and practices, which the
weather model does not try to capture. So the table also reports the correlation
against yield divided by its linear trend, which removes that slow climb.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import simulate as sim  # noqa: E402
from backend.schemas import SimulateRequest  # noqa: E402

LAT, LON, LABEL = 37.30, -120.48, "Merced, CA"
VALIDATION_DIR = ROOT / "data" / "validation"
CHART = ROOT / "docs" / "validation.png"
COUNTY = "Merced"

# Typical Merced field seasons for each crop, used for the 1 acre runs.
SEASONS = {
    "corn": (5, 9),                  # May to September
    "oats": (11, 4),                 # November to April
    "processing_tomatoes": (4, 8),   # April to August
    "almonds": (1, 12),
    "walnuts": (1, 12),
    "alfalfa_hay": (1, 12),
}
LABELS = {"corn": "Corn (grain)", "oats": "Oats", "processing_tomatoes": "Processing tomatoes",
          "almonds": "Almonds", "walnuts": "Walnuts", "alfalfa_hay": "Alfalfa hay"}


def load_yields() -> dict[str, dict[int, float]]:
    """crop -> {year: yield}, Merced County only."""
    out: dict[str, dict[int, float]] = {}
    sources: dict[str, str] = {}
    with (VALIDATION_DIR / "merced_yields.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            if r["yield"]:
                out.setdefault(r["crop"], {})[int(r["year"])] = float(r["yield"])
                sources[r["crop"]] = "merced_yields.csv"
    county_file = VALIDATION_DIR / "ca_county_yields.csv"
    if county_file.exists():
        with county_file.open(newline="") as f:
            for r in csv.DictReader(f):
                if r["county"] == COUNTY and r["yield"] and r["crop"] not in sources:
                    out.setdefault(r["crop"], {})[int(r["year"])] = float(r["yield"])
        for crop in out:
            sources.setdefault(crop, "ca_county_yields.csv")
    load_yields.sources = sources
    return out


def modeled_relative_yield(crop: str, years: list[int], wx) -> dict[int, float]:
    start, end = SEASONS[crop]
    req = SimulateRequest.model_validate({
        "location": {"lat": LAT, "lon": LON, "label": LABEL},
        "years": [years[0], years[-1]],
        "blocks": [{"id": "v", "crop": crop, "acres": 1, "irrigation": "drip",
                    "start_month": start, "end_month": end}],
        "optional": {"soil": "loam"},
    })
    bt = sim.run_backtest(req, wx)
    return {y: s.relative_yield for y, s in bt.seasons["v"].items() if y in years}


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def first_weather_year(crop: str, wx) -> int:
    start, end = SEASONS[crop]
    first = wx.index.min().year
    return first + 1 if start > end else first


def main() -> None:
    wx = sim.load_weather(LAT, LON)
    last_year = wx.index.max().year
    yields = load_yields()
    results = []
    for crop in sorted(yields):
        if crop not in SEASONS:
            continue
        lo = first_weather_year(crop, wx)
        years = sorted(y for y in yields[crop] if lo <= y <= last_year)
        if len(years) < 3:
            continue
        actual_raw = np.array([yields[crop][y] for y in years])
        anomaly = actual_raw / np.median(actual_raw)
        trend = np.polyval(np.polyfit(years, actual_raw, 1), years)
        detrended = actual_raw / trend
        model = modeled_relative_yield(crop, years, wx)
        modeled = np.array([model[y] for y in years])
        droughts = [y for y in sim.DROUGHT_YEARS if y in years]
        d_mask = np.isin(years, droughts)
        results.append({
            "crop": crop, "years": years, "modeled": modeled, "anomaly": anomaly,
            "detrended": detrended, "droughts": droughts,
            "r": pearson(modeled, anomaly), "r_detrended": pearson(modeled, detrended),
            "model_drought": float(modeled[d_mask].mean()) if d_mask.any() else None,
            "model_other": float(modeled[~d_mask].mean()),
            "actual_drought": float(detrended[d_mask].mean()) if d_mask.any() else None,
            "actual_other": float(detrended[~d_mask].mean()),
            "source": load_yields.sources[crop],
        })

    print_table(results)
    plot(results)
    print(f"\nChart saved to {CHART.relative_to(ROOT)}")


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:.0%}" if pct else f"{x:+.2f}"


def print_table(results: list[dict]) -> None:
    print("| Crop | Years compared | Range | r vs yield / median | r vs yield / trend "
          "| Drought years in data | Modeled, drought vs other | Actual (detrended), drought vs other |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        drought = ", ".join(map(str, r["droughts"])) or "none"
        model_cmp = (f"{_fmt(r['model_drought'], True)} vs {_fmt(r['model_other'], True)}"
                     if r["model_drought"] is not None else "n/a")
        actual_cmp = (f"{_fmt(r['actual_drought'], True)} vs {_fmt(r['actual_other'], True)}"
                      if r["actual_drought"] is not None else "n/a")
        print(f"| {LABELS[r['crop']]} | {len(r['years'])} | {r['years'][0]}-{r['years'][-1]} "
              f"| {_fmt(r['r'])} | {_fmt(r['r_detrended'])} | {drought} | {model_cmp} "
              f"| {actual_cmp} |")


def plot(results: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(results), 1, figsize=(10, 3.1 * len(results)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, r in zip(axes, results):
        for y in sim.DROUGHT_YEARS:
            ax.axvspan(y - 0.5, y + 0.5, color="#d9a441", alpha=0.25, lw=0)
        # Missing years become gaps instead of straight lines across them.
        full = np.arange(r["years"][0], r["years"][-1] + 1)
        idx = {y: i for i, y in enumerate(r["years"])}
        anomaly = [r["anomaly"][idx[y]] if y in idx else np.nan for y in full]
        modeled = [r["modeled"][idx[y]] if y in idx else np.nan for y in full]
        ax.plot(full, anomaly, "o-", color="#3b6e8f", lw=1.6, ms=4,
                label="Actual: NASS yield / median")
        ax.plot(full, modeled, "s-", color="#2e7d32", lw=1.6, ms=4,
                label="Modeled relative yield")
        ax.axhline(1.0, color="#999999", lw=0.8, ls=":")
        ax.set_title(f"{LABELS[r['crop']]}, Merced County  (r = {_fmt(r['r'])}, "
                     f"{len(r['years'])} years)", fontsize=11, loc="left")
        ax.set_ylabel("Share of normal")
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(loc="lower left", fontsize=9, frameon=False)
    axes[-1].set_xlabel("Year (shaded: drought years 2014, 2015, 2021, 2022)")
    fig.suptitle("YieldGenerator backtest vs real Merced County yields", fontsize=13, x=0.01,
                 ha="left")
    fig.tight_layout()
    CHART.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART, dpi=150)


if __name__ == "__main__":
    main()
