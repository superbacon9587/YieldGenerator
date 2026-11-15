import { Thermometer } from "lucide-react";
import { useYieldUnit } from "./YieldUnitContext.jsx";
import { formatWeightNumber, unitLabel } from "./yieldUnits.js";
import { averageLostPerAcre } from "./harvestLoss.js";
import "./yield.css";

/** "Average harvest lost to heat or water" summary card, in tons or lb per acre. */
export default function HarvestLossCard({ result }) {
  const { unit } = useYieldUnit();
  const lost = averageLostPerAcre(result);
  const value = formatWeightNumber(lost, unit, true);
  return (
    <div className="metric harvest-metric">
      <span className="metric-label">
        Average harvest lost to heat or water
        <Thermometer size={17} />
      </span>
      <strong>
        {value == null ? (
          "Not available"
        ) : (
          <>
            {value} <span>{unitLabel(unit, true)}</span>
          </>
        )}
      </strong>
      <small>Per year, compared with a full harvest</small>
    </div>
  );
}
