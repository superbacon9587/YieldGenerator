import { useState } from "react";
import { CalcInfo } from "../provenance/CalcPopover.jsx";
import { tableCells, tableHeaders, tableRecordId } from "../provenance/chartData.js";

const COLUMNS = ["harvest", "sales", "cost", "margin", "water", "yield"];

/**
 * The numbers behind the chart above it. `data` is the same getChartRows() result
 * the chart plots, so every cell is the bar it sits under; this component only
 * prints it. Average row cells open their calculation record.
 */
export default function ChartDataTable({ data, title }) {
  const [shown, setShown] = useState(true);
  if (!data?.rows.length) return null;
  const { scope, perAcre } = data.view;
  const head = tableHeaders(data.view);
  const cells = tableCells(data);
  const anyDrought = data.rows.some((r) => r.drought);
  const info = (metric, text) =>
    text && text !== "Not available" ? (
      <CalcInfo id={tableRecordId(scope, perAcre, metric)} display={text} />
    ) : null;
  return (
    <div className="chart-data">
      <div className="chart-data-head">
        <span className="caption">
          {title}
          {perAcre ? ", per acre" : ", totals"}
          {anyDrought && shown ? ". Shaded rows are drought years." : ""}
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
                <th>{head.year}</th>
                {COLUMNS.map((c) => (
                  <th key={c}>{head[c]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cells.rows.map((r, i) => (
                <tr key={r.year} className={data.rows[i].drought ? "drought-row" : ""}>
                  <th scope="row">{r.year}</th>
                  {COLUMNS.map((c) => (
                    <td key={c}>
                      {r[c]}
                      {c === "margin" && r.marginPct && <small className="table-pct">{r.marginPct}</small>}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="average-row">
                <th scope="row">Average</th>
                {COLUMNS.map((c) => (
                  <td key={c}>
                    {cells.average[c]}
                    {info(c, cells.average[c])}
                    {c === "margin" && cells.average.marginPct && (
                      <small className="table-pct">
                        {cells.average.marginPct}
                        {info("marginPct", cells.average.marginPct)}
                      </small>
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
