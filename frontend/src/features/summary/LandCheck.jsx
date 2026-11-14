import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { number } from "../../domain.js";
import { landCheck } from "./landBudget.js";
import "./summary.css";

/** Live line under the crop calendar: "Peak use: 55 of 70 acres (Jan)". */
export default function LandCheck({ blocks, available }) {
  const check = landCheck(blocks, available);
  if (!blocks.length) return null;
  const over = check.overMonths.length > 0;
  return (
    <div className={`land-check ${over ? "over" : "ok"}`} role="status">
      {over ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
      <div>
        <strong>
          Peak use: {number(check.peak, 1)}
          {check.available != null
            ? ` of ${number(check.available, 1)} acres`
            : " acres"}{" "}
          ({check.peakMonth})
        </strong>
        {over && (
          <span>
            Crops in the ground are above your available acreage in{" "}
            {check.overMonths.join(", ")}. You can still run the backtest.
          </span>
        )}
        {check.available == null && (
          <span>Enter your available acreage to check land use.</span>
        )}
      </div>
    </div>
  );
}
