import { availablePresets, presetYears } from "./landBudget.js";
import "./summary.css";

/** 5 / 10 / 20 / 30 / 40 years (from /api/meta) plus Custom. */
export default function PeriodPresets({ farm, setFarm, meta, children }) {
  const presets = availablePresets(meta);
  const period = farm.period ?? "custom";
  function choose(value) {
    if (value === "custom") setFarm({ ...farm, period: "custom" });
    else
      setFarm({
        ...farm,
        period: String(value),
        years: presetYears(value, meta),
      });
  }
  return (
    <div className="period-presets">
      <div className="segmented" role="group" aria-label="Backtest period">
        {presets.map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={period === String(p)}
            onClick={() => choose(p)}
          >
            {p} years
          </button>
        ))}
        <button
          type="button"
          aria-pressed={period === "custom"}
          onClick={() => choose("custom")}
        >
          Custom
        </button>
      </div>
      {period === "custom" ? (
        children
      ) : (
        <p className="caption">
          {farm.years[0]} to {farm.years[1]}, ending with the last full year of
          weather data.
        </p>
      )}
    </div>
  );
}
