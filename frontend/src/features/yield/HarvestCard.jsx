import { Wheat } from "lucide-react";
import { percent } from "../../domain.js";
import { useYieldUnit } from "./YieldUnitContext.jsx";
import { formatWeightNumber, unitLabel } from "./yieldUnits.js";
import "./yield.css";

/** "Average harvest per year" summary card, from summary_stats.avg_yield_tons. */
export default function HarvestCard({ result, relativeYield }) {
  const { unit } = useYieldUnit();
  const value = formatWeightNumber(
    result?.summary_stats?.avg_yield_tons,
    unit,
    false,
  );
  return (
    <div className="metric harvest-metric">
      <span className="metric-label">
        Average harvest per year
        <Wheat size={17} />
      </span>
      <strong>
        {value == null ? (
          "No yield data"
        ) : (
          <>
            {value} <span>{unitLabel(unit, false)}</span>
          </>
        )}
      </strong>
      <small>
        {relativeYield == null
          ? "Percent of full yield not available"
          : `${percent(relativeYield)} of full yield`}
      </small>
    </div>
  );
}
