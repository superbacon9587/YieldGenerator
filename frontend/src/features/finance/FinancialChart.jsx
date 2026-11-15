import { useRef, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { CROPS, money as formatMoney, number } from "../../domain.js";
import { CalculationLink } from "../provenance/CalculationDetails.jsx";
import {
  EXPENSES,
  fieldFor,
  financialYear,
  financialRows,
  cropSeries,
  expenseTotals,
  roundingDifference,
} from "./finance.js";
import "./finance.css";
const money = (value) => (value == null ? "Unavailable" : formatMoney(value));
const precise = (value) =>
  value == null
    ? "Not available"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });
const cents = (value) =>
  value == null
    ? "Not available"
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      });
const modeName = {
  profit: "Modeled margin",
  cost: "Estimated cost",
  sales: "Estimated sales",
};
function FinanceTooltip({ active, label, series, rows, result, mode }) {
  if (!active) return null;
  const row = rows.find((r) => String(r.year) === String(label));
  if (!row) return null;
  const excluded = financialYear(result, row.year)
    .entries.filter((e) => e.row[fieldFor(mode)] == null)
    .map((e) => e.name);
  return (
    <div className="finance-tooltip">
      <strong>{label}</strong>
      {series
        .filter((s) => row[s.key] != null)
        .map((s) => (
          <p key={s.key}>
            <span style={{ color: s.color }}>●</span> {s.label}:{" "}
            <b>{money(row[s.key])}</b>
          </p>
        ))}
      <p className="finance-tooltip-total">
        Included farm total: <b>{money(row.net)}</b>
      </p>
      {excluded.length > 0 && (
        <small>Unavailable: {excluded.join(", ")}. Not counted as zero.</small>
      )}
      <small>Choose this year below for the full breakdown.</small>
    </div>
  );
}
function SalesSteps({ entry, year }) {
  const r = entry?.trace;
  if (!entry) return null;
  if (!r)
    return (
      <p className="calculation-warning">
        The backend did not return the inputs needed to explain {entry.name} in{" "}
        {year}. Rerun using the updated live backend. The displayed sales value
        alone cannot establish its source.
      </p>
    );
  const included = entry.row.revenue != null;
  return (
    <div className="sales-steps">
      <h3>
        {entry.name} sales in {year}, step by step
      </h3>
      {!included && (
        <p className="calculation-warning">
          This crop is excluded from financial totals because required financial
          inputs are incomplete. Its harvest may still be available. A missing
          dollar value is not $0.
        </p>
      )}
      <ol>
        <li>
          <span>Reference yield</span>
          <strong>
            {precise(r.baseline_yield?.value)} {r.baseline_yield?.unit ?? ""}
          </strong>
          <p>
            {r.baseline_yield?.source ?? "No baseline available."} This is a
            reference median, not this farmer's recorded harvest.
          </p>
        </li>
        <li>
          <span>Adjust for this season's weather</span>
          <strong>
            {precise(r.baseline_tons_per_acre)} US tons/acre ×{" "}
            {precise(r.displayed.relative_yield)} ÷{" "}
            {precise(r.median_relative_yield)} ={" "}
            {precise(r.harvest_tons_per_acre)} US tons/acre
          </strong>
          <p>
            The first fraction is this year's modeled yield relative to an
            unstressed crop. The divisor is the median fraction under uncapped
            water across the selected years. It stays fixed when your water
            limit changes. The ratio compares this year with the reference
            median, so the two percentages have different meanings.
          </p>
          <a href={r.weather_source.url} target="_blank" rel="noreferrer">
            NASA weather used: {r.season_start} to {r.season_end}
          </a>
        </li>
        <li>
          <span>Multiply by your planted area</span>
          <strong>
            {precise(r.harvest_tons_per_acre)} US tons/acre ×{" "}
            {precise(entry.acres)} acres = {precise(r.harvest_tons)} US tons
          </strong>
          <p>
            One US short ton is 2,000 lb. These quantities are modeled, not
            harvest records.
          </p>
        </li>
        <li>
          <span>Match the crop price's unit and year</span>
          <p>
            {precise(r.harvest_tons)} US tons x 2,000 lb/ton /{" "}
            {precise(r.pounds_per_sale_unit)} lb per sale unit ={" "}
            {precise(r.sale_quantity)} sale units.
          </p>
          <strong>
            {precise(r.sale_quantity)}{" "}
            {r.crop_price?.unit.replace(/^\$\s*\/\s*/, "") ?? "sale units"} ×{" "}
            {precise(r.crop_price?.value)} {r.crop_price?.unit ?? ""}
          </strong>
          <p>
            Price source year: <b>{r.crop_price?.year ?? "unavailable"}</b>,
            separate from the weather year <b>{year}</b>. Current-price mode
            intentionally reuses the latest stored price across weather years;
            historical mode uses that year or its nearest available price.
          </p>
          <a href={r.price_source.url} target="_blank" rel="noreferrer">
            Open the crop-price input extract
          </a>
        </li>
        <li>
          <span>Estimated crop sales included in the total</span>
          <strong>
            {included ? cents(r.revenue_unrounded) : "Not available"}
          </strong>
          <p>
            The ordinary crop row rounds this to {money(entry.row.revenue)}. The
            farm total adds financially supported crop entries, not every
            harvest entry. Displayed inputs are rounded; the calculation keeps
            more precision.
          </p>
        </li>
      </ol>
      {(r.source_warnings ?? []).map((note) => (
        <p className="calculation-warning" key={note}>
          {note}
        </p>
      ))}
      <CalculationLink metric="revenue" blockId={entry.id} year={year}>
        Inspect exact numbers and matching source records
      </CalculationLink>
    </div>
  );
}
export default function FinancialChart({ result, mode, year, onYear }) {
  const detailRef = useRef(null);
  const [grouping, setGrouping] = useState("crop");
  const [cropId, setCropId] = useState(result.blocks[0]?.id);
  const { totals, entries } = financialYear(result, year);
  const selected = entries.find((e) => e.id === cropId) ?? entries[0];
  const expense = expenseTotals(entries);
  const effectiveGrouping =
    mode === "cost" && grouping === "expense" && expense ? "expense" : "crop";
  const rows = financialRows(result, mode, effectiveGrouping);
  const series =
    effectiveGrouping === "expense" ? EXPENSES : cropSeries(result, mode);
  const excluded = entries
    .filter((e) => e.row[fieldFor(mode)] == null)
    .map((e) => e.name);
  return (
    <div className="finance-explorer">
      <p className="finance-coverage">
        <b>Profit here means margin above modeled operating costs.</b> Separate
        cash/non-cash overhead and establishment are excluded. This is not net
        farm income.
      </p>
      <p className="finance-guide">
        <b>Follow the money:</b> choose a view, choose a year, then read the
        crop totals below. In Sales, pick a crop to follow its calculation and
        sources.
      </p>
      {mode === "cost" && (
        <div className="segmented finance-grouping" aria-label="Cost breakdown">
          <button
            aria-pressed={effectiveGrouping === "crop"}
            onClick={() => setGrouping("crop")}
          >
            By crop
          </button>
          <button
            aria-pressed={effectiveGrouping === "expense"}
            disabled={!expense}
            onClick={() => setGrouping("expense")}
          >
            By expense
          </button>
        </div>
      )}
      {mode === "cost" && !expense && (
        <p className="caption">
          Expense categories are unavailable in this response. Crop costs are
          still shown; rerun with the updated live backend for expense details.
        </p>
      )}
      <div
        className="chart-wrap finance-chart"
        role="img"
        aria-label={`${modeName[mode]} by year, with ${effectiveGrouping === "expense" ? "expense" : "crop"} contributions. Exact values are in the breakdown below.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            stackOffset="sign"
            margin={{ top: 16, right: 15, left: 0, bottom: 8 }}
            onClick={(state) => {
              const clicked = Number(state?.activeLabel);
              if (result.years.includes(clicked)) onYear(clicked);
            }}
          >
            <CartesianGrid
              strokeDasharray="3 4"
              vertical={false}
              stroke="#e5e9df"
            />
            <XAxis dataKey="year" minTickGap={28} tick={{ fontSize: 11 }} />
            <YAxis
              width={65}
              tickFormatter={(v) => `$${number(v / 1000)}k`}
              tick={{ fontSize: 11 }}
            />
            <ReferenceLine y={0} stroke="#829082" />
            {(result.summary.drought_years ?? []).map((y) => (
              <ReferenceArea
                key={y}
                x1={y}
                x2={y + 1}
                fill="#d7be85"
                fillOpacity={0.16}
              />
            ))}
            <Tooltip
              content={
                <FinanceTooltip
                  series={series}
                  rows={rows}
                  result={result}
                  mode={mode}
                />
              }
            />
            <Legend
              iconType="circle"
              wrapperStyle={{ fontSize: 12, paddingTop: 12 }}
            />
            {series.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId="contributions"
                fill={s.color}
                isAnimationActive={false}
              />
            ))}
            <Line
              dataKey="net"
              name="Included farm total"
              stroke="#243a2c"
              strokeWidth={1.5}
              dot={{ r: 3, fill: "#243a2c" }}
              isAnimationActive={false}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="caption">
        {mode === "profit"
          ? "Crop gains appear above zero; crop losses appear below. The dark line is the net farm margin after adding gains and losses."
          : "Colored segments show what adds up to the farm total; the dark line marks that total."}{" "}
        Shaded years are backend-flagged drought years. Differences up to $1 can
        come from rounding crop rows separately.
      </p>
      {excluded.length > 0 && (
        <p className="finance-coverage">
          <b>Partial financial total:</b> {excluded.join(", ")}{" "}
          {excluded.length === 1 ? "is" : "are"} unavailable in {year} and
          excluded, not counted as zero. Harvest and water totals can cover more
          crops.
        </p>
      )}
      <div className="finance-year-heading">
        <h3>{year}: where the money comes from and goes</h3>
        <label>
          Financial year
          <select value={year} onChange={(e) => onYear(Number(e.target.value))}>
            {result.years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="finance-table-scroll">
        <table className="finance-table">
          <thead>
            <tr>
              <th>Crop entry</th>
              <th>Sales</th>
              <th>Estimated cost</th>
              <th>Contribution to net margin</th>
              <th>Calculation</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <th>
                  <span
                    className="crop-dot"
                    style={{ background: CROPS[e.crop]?.color }}
                  />
                  {e.name}
                  <small>
                    {e.id} · {number(e.acres, 1)} acres
                  </small>
                </th>
                <td>{money(e.row.revenue)}</td>
                <td>{money(e.row.cost)}</td>
                <td
                  className={
                    e.row.profit == null
                      ? ""
                      : e.row.profit < 0
                        ? "finance-negative"
                        : "finance-positive"
                  }
                >
                  {money(e.row.profit)}
                </td>
                <td>
                  <button
                    className="text-button"
                    onClick={() => {
                      setCropId(e.id);
                      requestAnimationFrame(() => {
                        detailRef.current?.scrollIntoView({
                          behavior: "smooth",
                          block: "start",
                        });
                        detailRef.current?.focus({ preventScroll: true });
                      });
                    }}
                  >
                    Explain {e.name.toLowerCase()}
                  </button>
                </td>
              </tr>
            ))}
            {["revenue", "cost", "profit"].some((field) =>
              roundingDifference(entries, totals[field], field),
            ) && (
              <tr className="finance-rounding">
                <th>Rounding adjustment</th>
                {["revenue", "cost", "profit"].map((field) => (
                  <td key={field}>
                    {money(roundingDifference(entries, totals[field], field))}
                  </td>
                ))}
                <td />
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th>Included farm total</th>
              <td>{money(totals.revenue)}</td>
              <td>{money(totals.cost)}</td>
              <td>{money(totals.profit)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="finance-equation">
        {year}:{" "}
        <b>
          {money(totals.revenue)} sales − {money(totals.cost)} cost ={" "}
          {money(totals.profit)} modeled margin
        </b>
        . Dollar rows are rounded, so subtraction can differ by $1.
      </p>
      <div className="finance-crop-picker">
        <label>
          Crop to explain
          <select
            value={selected?.id}
            onChange={(e) => setCropId(e.target.value)}
          >
            {entries.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} · {e.id}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div ref={detailRef} tabIndex={-1} className="finance-detail-target">
        {mode === "sales" ? (
          <SalesSteps entry={selected} year={year} />
        ) : mode === "cost" ? (
          <section className="expense-details">
            <h3>
              {selected?.name} cost drivers in {year}
            </h3>
            {selected?.row.cost == null ? (
              <p>
                Cost is unavailable for this crop. It is excluded from the
                farm's financial total.
              </p>
            ) : selected.trace ? (
              <>
                <dl>
                  <div>
                    <dt>Regional non-water production cost</dt>
                    <dd>{cents(selected.trace.production_cost_excl_water)}</dd>
                  </div>
                  <div>
                    <dt>Surface water</dt>
                    <dd>{cents(selected.trace.surface_water_cost)}</dd>
                  </div>
                  <div>
                    <dt>Groundwater pumping</dt>
                    <dd>{cents(selected.trace.groundwater_cost)}</dd>
                  </div>
                  <div>
                    <dt>Total, before whole-dollar rounding</dt>
                    <dd>{cents(selected.trace.cost_unrounded)}</dd>
                  </div>
                </dl>
                <p>
                  Non-water cost:{" "}
                  {cents(selected.trace.production_cost_per_acre)}
                  /acre × {number(selected.acres, 1)} acres. Source:{" "}
                  {selected.trace.production_cost_source?.source}.
                </p>
                <p>
                  Water cost depends on modeled applied water, source shares,
                  surface-water price, pumping lift, pump efficiency, and
                  electricity price. It is not a meter reading or invoice.
                </p>
                {selected.trace.verified_cost_study && (
                  <details className="study-expense-detail">
                    <summary>
                      See verified PDF expense categories for your acreage
                    </summary>
                    <p>
                      <a
                        href={`${selected.trace.verified_cost_study.url}#page=${selected.trace.verified_cost_study.pdf_page}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {selected.trace.verified_cost_study.title},{" "}
                        {selected.trace.verified_cost_study.table}, page{" "}
                        {selected.trace.verified_cost_study.pdf_page}
                      </a>
                    </p>
                    <div className="finance-table-scroll">
                      <table className="finance-table">
                        <thead>
                          <tr>
                            <th>Study category</th>
                            <th>Reference per acre</th>
                            <th>Your {selected.acres} acres</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(
                            selected.trace.verified_cost_study
                              .nonwater_categories_per_acre,
                          ).map(([name, value]) => (
                            <tr key={name}>
                              <th>{name}</th>
                              <td>{cents(value)}</td>
                              <td>{cents(value * selected.acres)}</td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr>
                            <th>Non-water operating costs</th>
                            <td>
                              {cents(selected.trace.production_cost_per_acre)}
                            </td>
                            <td>
                              {cents(selected.trace.production_cost_excl_water)}
                            </td>
                          </tr>
                        </tfoot>
                      </table>
                    </div>
                    {selected.trace.verified_cost_study.limitations.map(
                      (note) => (
                        <p className="caption" key={note}>
                          {note}
                        </p>
                      ),
                    )}
                  </details>
                )}
              </>
            ) : (
              <p>Exact expense inputs are not in this response.</p>
            )}
            <p className="calculation-warning">
              These are reference operating costs, not your expenses. Verified
              PDF categories are shown where available; unaudited crops retain a
              bundled non-water amount. The reference amounts scale with acres,
              but are not repriced for your actual harvest or equipment.
            </p>
            {selected?.trace?.source_warnings?.map((note) => (
              <p className="calculation-warning" key={note}>
                {note}
              </p>
            ))}
            <CalculationLink metric="cost" blockId={selected?.id} year={year}>
              Inspect expense arithmetic and source records
            </CalculationLink>
          </section>
        ) : (
          <section className="margin-details">
            <h3>
              {selected?.name}'s contribution in {year}
            </h3>
            <p>
              <b>
                {money(selected?.row.revenue)} sales −{" "}
                {money(selected?.row.cost)} cost = {money(selected?.row.profit)}{" "}
                margin.
              </b>{" "}
              A loss subtracts from other crops' gains; it is not hidden inside
              the total.
            </p>
            <CalculationLink metric="profit" blockId={selected?.id} year={year}>
              Inspect this crop's sales, costs, and sources
            </CalculationLink>
          </section>
        )}
      </div>
    </div>
  );
}
