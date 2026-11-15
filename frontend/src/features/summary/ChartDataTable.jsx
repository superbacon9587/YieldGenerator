import { useState } from "react";
import { CalcInfo } from "../provenance/CalcPopover.jsx";
import { tableCells, tableHeaders, tableRecordId, chartGuide } from "../provenance/chartData.js";

import { sourceParts } from "../provenance/calcRecords.js";

/**
 * The numbers behind the chart above it. `data` is the same getChartRows() result
 * the chart plots, so every cell is the bar it sits under; this component only
 * prints it. Average row cells open their calculation record.
 */
export default function ChartDataTable({ data, title, result }) {
  const [shown, setShown] = useState(true);
  if (!data?.rows.length) return null;
  const { scope, perAcre } = data.view;
  const guide = chartGuide(data.view);
  const columns = guide.columns;
  const record = result?.calculations?.[tableRecordId(scope, perAcre, data.totalKey)];
  const links = [...new Map((record?.inputs ?? []).flatMap(input => sourceParts(input).links).map(link => [link.url,link])).values()];
  const head = tableHeaders(data.view);
  const cells = tableCells(data);
  const anyDrought = data.rows.some((r) => r.drought);
  const info = (metric, text) =>
    text && text !== "Not available" ? (
      <CalcInfo id={tableRecordId(scope, perAcre, metric)} display={text} />
    ) : null;
  return (
    <div className="chart-data">
      <aside className="chart-guide" aria-label="Graph formula and data sources">
        <p><strong>Formula:</strong> {guide.formula}</p>
        <p><strong>Data:</strong> {guide.sources}</p>
        {links.length > 0 && <p className="calc-links">{links.map(link => <a key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.label}</a>)}</p>}
        <p className="caption">{guide.notes}</p>
      </aside>
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
                {columns.map((c) => (
                  <th key={c}>{head[c]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cells.rows.map((r, i) => (
                <tr key={r.year} className={data.rows[i].drought ? "drought-row" : ""}>
                  <th scope="row">{r.year}</th>
                  {columns.map((c) => (
                    <td key={c}>
                      {r[c]}

                    </td>
                  ))}
                </tr>
              ))}
              <tr className="average-row">
                <th scope="row">Average</th>
                {columns.map((c) => (
                  <td key={c}>
                    {cells.average[c]}
                    {info(c, cells.average[c])}

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
