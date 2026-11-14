import { useState } from "react";
import { CROPS, IRRIGATION, MONTHS, number } from "../../domain.js";
import { alternativeLabel, comparisonGroups, difference } from "./model.js";
import "./comparisons.css";

function Delta({ value, kind }) {
  const { text, tone } = difference(value, kind);
  return <strong className={`system-delta ${tone}`}>{text}</strong>;
}
function CropComparisons({ block, rows, onView, disabled }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? rows : rows.slice(0, 3);
  const notes = [...new Set(rows.map((row) => row.excludes).filter(Boolean))];
  return (
    <article className="system-crop-card">
      <header className="system-crop-heading">
        <div>
          <span
            className="system-crop-dot"
            style={{ background: CROPS[block.crop]?.color ?? "#75836a" }}
            aria-hidden="true"
          />
          <h3>{CROPS[block.crop]?.name ?? block.crop}</h3>
          <span className="chip">{block.id}</span>
        </div>
        <p>
          {number(block.acres, 1)} acres ·{" "}
          {IRRIGATION[block.irrigation] ?? block.irrigation} ·{" "}
          {MONTHS[block.start_month - 1]} to {MONTHS[block.end_month - 1]}
        </p>
      </header>
      <div
        className="system-table-scroll"
        role="region"
        aria-label={`${CROPS[block.crop]?.name ?? block.crop} system comparisons`}
        tabIndex={0}
      >
        <table className="system-table">
          <thead>
            <tr>
              <th scope="col">Alternative</th>
              <th scope="col">Profit / year change</th>
              <th scope="col">Yield change</th>
              <th scope="col">Water / year change</th>
              <th scope="col">Worst-year profit change</th>
              <th scope="col">
                <span className="sr-only">Open comparison</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr
                key={`${row.kind}-${row.alternative.irrigation}-${row.alternative.start_month}-${index}`}
              >
                <th scope="row">{alternativeLabel(row)}</th>
                <td data-label="Profit / year change">
                  <Delta value={row.avg_profit_change} kind="money" />
                </td>
                <td data-label="Yield change">
                  <Delta
                    value={row.avg_relative_yield_change_pts}
                    kind="yield"
                  />
                </td>
                <td data-label="Water / year change">
                  <Delta value={row.avg_water_change_af} kind="water" />
                </td>
                <td data-label="Worst-year profit change">
                  <Delta value={row.worst_year_profit_change} kind="money" />
                </td>
                <td>
                  <button
                    className="secondary"
                    disabled={disabled}
                    onClick={() => onView(row)}
                    aria-label={`View ${CROPS[block.crop]?.name ?? block.crop}: ${alternativeLabel(row)} in what-if`}
                  >
                    View in what-if
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 3 && (
        <button
          className="text-button system-show-all"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show fewer" : `Show all ${rows.length} comparisons`}
        </button>
      )}
      <div className="system-exclusions">
        {notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    </article>
  );
}
export default function SystemComparisons({
  farm,
  comparisons,
  onView,
  disabled = false,
  mock = false,
}) {
  const groups = comparisonGroups(farm, comparisons);
  if (!groups.length) return null;
  return (
    <section
      className="panel system-comparisons"
      id="system-comparisons"
      aria-labelledby="system-comparisons-title"
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">SAME FARM. ONE CHANGE.</span>
          <h2 id="system-comparisons-title">System comparisons</h2>
        </div>
        <span className="chip">
          {mock ? "Synthetic demo" : "Live model results"}
        </span>
      </div>
      <p className="subtle">
        How each crop's results would have changed under a different irrigation
        system or planting window, over the same years and weather.
      </p>
      <p className="caption">
        Changes are for the named crop entry, compared with its current setup.
        Yield is a percentage-point change, not pounds or tons harvested. These
        are modeled comparisons, not recommendations.
      </p>
      {groups.map(({ block, rows }) => (
        <CropComparisons
          key={block.id}
          block={block}
          rows={rows}
          onView={onView}
          disabled={disabled}
        />
      ))}
    </section>
  );
}
