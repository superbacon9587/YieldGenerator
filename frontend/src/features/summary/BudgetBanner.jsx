import { AlertTriangle } from "lucide-react";
import { budgetMessage } from "./landBudget.js";
import "./summary.css";

/** Amber note when farm cost was above the yearly budget in any year. */
export default function BudgetBanner({ result }) {
  const message = budgetMessage(result.budget, result.years.length);
  if (!message) return null;
  return (
    <div className="budget-banner" role="note">
      <AlertTriangle size={18} />
      <div>
        <strong>{message}</strong>
        <span>
          Those years are outlined in amber on the Profit chart. Farm cost only
          includes crops with price data.
        </span>
      </div>
    </div>
  );
}
