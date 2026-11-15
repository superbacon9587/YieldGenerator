import { Wheat } from "lucide-react";
import { CalcInfo } from "../provenance/CalcPopover.jsx";
import { useYieldUnit } from "./YieldUnitContext.jsx";
import { unitLabel } from "./yieldUnits.js";
import { formatCell, getChartRows } from "../provenance/chartData.js";
import "./yield.css";

/** "Average harvest per year" summary card, from summary_stats.avg_yield_tons. */
export default function HarvestCard({ result, relativeYield }) {
  const { unit } = useYieldUnit();
  // Same number as the Average row of the whole-farm harvest table, in the chosen unit.
  const avg = getChartRows(result, { chart: "yield", scope: "farm", unit }).average.harvest;
  const value = avg == null ? null : formatCell("harvest", avg, { unit });
  return (
    <div className="metric harvest-metric">
      <span className="metric-label">
        Estimated harvest per year
        <CalcInfo
          id="summary.avg_yield_tons"
          display={value == null ? undefined : `${value} ${unitLabel(unit, false)}`}
        />
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
      <small>Whole farm, average per year</small>
    </div>
  );
}
