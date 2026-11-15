import {
  Droplets,
  PiggyBank,
  TrendingUp,
  Wallet,
  CalendarRange,
} from "lucide-react";
import { money, number, percent } from "../../domain.js";
import { summaryOf } from "./landBudget.js";
import { MetricInfo } from "../provenance/CalculationDetails.jsx";
import HarvestCard from "../yield/HarvestCard.jsx";
import "./summary.css";

function Card({ label, value, detail, icon: Icon }) {
  return (
    <div className="metric summary-card">
      <span className="metric-label">
        {label}
        <MetricInfo
          metric={
            label.startsWith("Total")
              ? "total_profit"
              : label.includes("margin")
                ? "avg_profit"
                : label.includes("water")
                  ? "avg_water"
                  : label.includes("relative")
                    ? "avg_relative"
                    : "summary"
          }
          label={label}
        />
        <Icon size={17} />
      </span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

/**
 * Top row: average harvest per year (Part C), total profit, average profit,
 * average yield, average water, best and worst year.
 */
export default function SummaryCards({ result }) {
  const s = summaryOf(result);
  const years = s.years_count;
  return (
    <div className="metrics-grid summary-grid">
      <HarvestCard
        result={{ summary_stats: s }}
        relativeYield={s.avg_relative_yield}
      />
      <Card
        label="Total operating margin"
        value={money(s.total_profit)}
        detail={`Over ${years} years`}
        icon={PiggyBank}
      />
      <Card
        label="Operating margin per year"
        value={money(s.avg_profit)}
        detail={
          s.avg_cost == null
            ? "Cost not available"
            : `Estimated cost ${money(s.avg_cost)}/year`
        }
        icon={Wallet}
      />
      <Card
        label="Average relative yield"
        value={percent(s.avg_relative_yield)}
        detail="Share of an unstressed year, area weighted"
        icon={TrendingUp}
      />
      <Card
        label="Average water per year"
        value={
          s.avg_water_applied_af == null
            ? "Not available"
            : `${number(s.avg_water_applied_af, 1)}`
        }
        detail="acre-feet applied"
        icon={Droplets}
      />
      <div className="metric year-metric summary-card">
        <span className="metric-label">
          Best and worst year
          <MetricInfo metric="ranking" />
          <CalendarRange size={17} />
        </span>
        <div>
          <span>
            <small>Best year</small>
            <strong>{result.summary?.best_year ?? "Not available"}</strong>
          </span>
          <span>
            <small>Worst year</small>
            <strong>{result.summary?.worst_year ?? "Not available"}</strong>
          </span>
        </div>
        <small>Ranking method is listed in assumptions</small>
      </div>
    </div>
  );
}
