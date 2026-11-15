import {
  Droplets,
  PiggyBank,
  TrendingUp,
  Wallet,
  CalendarRange,
} from "lucide-react";
import { money, number, percent } from "../../domain.js";
import { summaryOf } from "./landBudget.js";
import { CalcInfo } from "../provenance/CalcPopover.jsx";
import HarvestCard from "../yield/HarvestCard.jsx";
import "./summary.css";

function Card({ label, value, detail, icon: Icon, id, display }) {
  return (
    <div className="metric summary-card">
      <span className="metric-label">
        {label}
        <CalcInfo id={id} display={display ?? value} />
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
      <HarvestCard result={result} relativeYield={s.avg_relative_yield} />
      <Card
        label="Total estimated margin"
        id="summary.total_profit"
        value={money(s.total_profit)}
        detail={`Over ${years} years`}
        icon={PiggyBank}
      />
      <Card
        label="Estimated margin per year"
        id="summary.avg_profit"
        value={money(s.avg_profit)}
        detail={
          s.avg_cost == null ? (
            "Cost not available"
          ) : (
            <>
              Estimated cost {money(s.avg_cost)}/year
              <CalcInfo id="summary.avg_cost" display={money(s.avg_cost)} />
            </>
          )
        }
        icon={Wallet}
      />
      <Card
        label="Average relative yield"
        id="summary.avg_relative_yield"
        value={percent(s.avg_relative_yield)}
        detail="Share of an unstressed year, area weighted"
        icon={TrendingUp}
      />
      <Card
        label="Average water per year"
        id="summary.avg_water_applied_af"
        display={`${number(s.avg_water_applied_af, 1)} acre-ft`}
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
          <CalendarRange size={17} />
        </span>
        <div>
          <span>
            <small>Best year</small>
            <strong>
              {result.summary?.best_year ?? "Not available"}
              <CalcInfo id="summary.best_year" />
            </strong>
          </span>
          <span>
            <small>Worst year</small>
            <strong>
              {result.summary?.worst_year ?? "Not available"}
              <CalcInfo id="summary.worst_year" />
            </strong>
          </span>
        </div>
        <small>Ranking method is listed in assumptions</small>
      </div>
    </div>
  );
}
