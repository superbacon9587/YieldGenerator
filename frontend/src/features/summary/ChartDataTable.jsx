import { useState } from "react";
import { CalcInfo } from "../provenance/CalcPopover.jsx";
import { useYieldUnit } from "../yield/YieldUnitContext.jsx";
import { formatWeightNumber, unitLabel } from "../yield/yieldUnits.js";
import { averageRow, tableRecordId, tableRows } from "./chartTable.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const NA = "Not available";
const dollars = (v) =>
  finite(v)
    ? `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
    : NA;
const fixed = (v, d) =>
  finite(v)
    ? v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })
    : NA;

/**
 * Year by year numbers behind the chart above it: Year, Harvest, Sales, Cost,
 * Margin, Water, Yield, plus a bold Average row whose cells open their calculation.
 */
export default function ChartDataTable({ result, scope = "farm", perAcre = false, title }) {
  const [shown, setShown] = useState(true);
  const { unit } = useYieldUnit();
  const rows = tableRows(result, scope, perAcre);
  if (!rows.length) return null;
  const records = result.calculations ?? {};
  const local = averageRow(rows);
  const recordValue = (metric) => records[tableRecordId(scope, perAcre, metric)]?.value;
  // Average cells show the backend record value when present, so the cell and its popover agree.
  const avg = Object.fromEntries(
    Object.keys(local).map((m) => {
      const v = recordValue(m === "marginPct" ? "margin_pct" : m);
      return [m, finite(v) ? v : local[m]];
    }),
  );
  const drought = new Set(result.summary?.drought_years ?? []);
  const perText = perAcre ? "/acre" : "";
  const fmt = {
    harvest: (v) => (finite(v) ? formatWeightNumber(v, unit, perAcre) : NA),
    sales: dollars,
    cost: dollars,
    margin: dollars,
    water: (v) => fixed(v, perAcre ? 2 : 1),
    yield: (v) => (finite(v) ? `${fixed(v, 1)}%` : NA),
    marginPct: (v) => (finite(v) ? `${fixed(v, 1)}%` : ""),
  };
  const cell = (m, v, average) => (
    <td>
      {fmt[m](v)}
      {average && finite(v) && (
        <CalcInfo
          id={tableRecordId(scope, perAcre, m)}
          display={m === "harvest" ? `${fmt.harvest(v)} ${unitLabel(unit, perAcre)}` : fmt[m](v)}
        />
      )}
    </td>
  );
  const marginCell = (r, average) => (
    <td>
      {fmt.margin(r.margin)}
      {average && finite(r.margin) && (
        <CalcInfo id={tableRecordId(scope, perAcre, "margin")} display={fmt.margin(r.margin)} />
      )}
      {finite(r.marginPct) && (
        <small className="table-pct">
          {fmt.marginPct(r.marginPct)}
          {average && (
            <CalcInfo
              id={tableRecordId(scope, perAcre, "margin_pct")}
              display={fmt.marginPct(r.marginPct)}
            />
          )}
        </small>
      )}
    </td>
  );
  const row = (r, average = false) => (
    <tr
      key={average ? "average" : r.year}
      className={average ? "average-row" : drought.has(r.year) ? "drought-row" : ""}
    >
      <th scope="row">{average ? "Average" : r.year}</th>
      {cell("harvest", r.harvest, average)}
      {cell("sales", r.sales, average)}
      {cell("cost", r.cost, average)}
      {marginCell(r, average)}
      {cell("water", r.water, average)}
      {cell("yield", r.yield, average)}
    </tr>
  );
  return (
    <div className="chart-data">
      <div className="chart-data-head">
        <span className="caption">
          {title}
          {perAcre ? ", per acre" : ", totals"}
          {drought.size > 0 && shown ? ". Shaded rows are drought years." : ""}
        </span>
        <button
          type="button"
          className="text-button"
          aria-expanded={shown}
          onClick={() => setShown(!shown)}
        >
          {shown ? "Hide table" : "Show table"}
        </button>
      </div>
      {shown && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Year</th>
                <th>Harvest ({unitLabel(unit, perAcre)})</th>
                <th>Sales{perAcre ? " ($/acre)" : ""}</th>
                <th>Cost{perAcre ? " ($/acre)" : ""}</th>
                <th>Margin{perAcre ? " ($/acre)" : ""}</th>
                <th>Water (acre-ft{perText})</th>
                <th>Yield (% of potential)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => row(r))}
              {row({ ...avg }, true)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
