import { CROPS } from "../../domain.js";
import { CalcInfo } from "./CalcPopover.jsx";
import { formatRecordValue } from "./calcRecords.js";

/** "Estimated sales - estimated cost = modeled margin per year", with a button on each number. */
export default function MoneyExplanation({ result }) {
  const c = result.calculations ?? {};
  const d = result.calculation_details;
  const sales = c["summary.avg_revenue"];
  const cost = c["summary.avg_cost"];
  const margin = c["summary.avg_profit"];
  if (!sales || !cost || !margin) return null;
  const excluded = d?.excluded_financial_blocks ?? [];
  return (
    <div className="money-explanation" role="note">
      <strong>
        Estimated sales {formatRecordValue(sales)}
        <CalcInfo record={sales} /> - estimated cost {formatRecordValue(cost)}
        <CalcInfo record={cost} /> = modeled margin {formatRecordValue(margin)}
        <CalcInfo record={margin} /> per year
      </strong>
      <p>
        Costs use regional reference studies and modeled water, not this farm's
        recorded expenses.{" "}
        {excluded.length
          ? `Partial financial totals: ${excluded.map((b) => CROPS[b.crop]?.name ?? b.crop).join(", ")} left out because financial inputs are missing.`
          : "All crop entries have financial data."}{" "}
        The budget is a spending limit, not an operating-cost input.
      </p>
    </div>
  );
}
