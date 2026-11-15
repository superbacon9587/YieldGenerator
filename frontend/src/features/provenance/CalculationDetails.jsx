import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Info, X } from "lucide-react";
import { CROPS, money, number } from "../../domain.js";
import "./provenance.css";
import { periodCalculation } from "./audit.js";
const Context = createContext(null);
const n = (value) =>
  value == null
    ? "Not available"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: 6 });
const preciseMoney = (value) =>
  value == null
    ? "Not available"
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      });
const titles = {
  harvest: "Harvest per acre and total harvest",
  profit: "Revenue, estimated cost, and modeled margin",
  cost: "Estimated production cost",
  revenue: "Estimated sales revenue",
  water: "Water applied",
  relative: "Relative yield",
  etc: "Crop water use",
  rain: "Effective rain",
  heat: "Heat days",
  gdd: "Growing degree days",
  summary: "Period totals and averages",
  ranking: "Best and worst year",
};
export function MetricInfo({ metric = "summary", blockId, year, label }) {
  const open = useContext(Context);
  if (!open) return null;
  return (
    <button
      type="button"
      className="metric-info"
      aria-label={`How calculated: ${label ?? titles[metric]}${year ? `, ${year}` : ""}${blockId ? `, ${blockId}` : ""}`}
      onClick={() => open({ metric, blockId, year })}
    >
      <Info size={15} aria-hidden="true" />
    </button>
  );
}
export function CalculationLink({
  metric = "summary",
  blockId,
  year,
  children,
}) {
  const open = useContext(Context);
  if (!open) return null;
  return (
    <button
      type="button"
      className="text-button"
      onClick={() => open({ metric, blockId, year })}
    >
      {children ?? "View source records and exact calculation"}
    </button>
  );
}
function Source({ item }) {
  if (!item) return null;
  return (
    <details className="calculation-source">
      <summary>
        <a href={item.url} target="_blank" rel="noreferrer">
          {item.label}
        </a>
        {item.records?.length
          ? ` · ${item.records.length} input record(s)`
          : ""}
      </summary>
      {item.records?.length > 0 && (
        <pre>{JSON.stringify(item.records, null, 2)}</pre>
      )}
    </details>
  );
}
function Equations({ metric, row: r, block }) {
  if (!r)
    return (
      <p>
        Calculation inputs are unavailable for this crop and year. Rerun with a
        backend that returns calculation details.
      </p>
    );
  const h = (
    <>
      <p>
        Baseline:{" "}
        <b>
          {n(r.baseline_yield?.value)} {r.baseline_yield?.unit}
        </b>
        . {r.baseline_yield?.source ?? "No baseline source available."}
      </p>
      <p>
        Convert baseline to US short tons per acre:{" "}
        <b>{n(r.baseline_tons_per_acre)}</b>. One US short ton is 2,000 lb;
        bushel conversions use crop-specific weights.
      </p>
      <p className="equation">
        {n(r.baseline_tons_per_acre)} × {n(r.displayed.relative_yield)} ÷{" "}
        {n(r.median_relative_yield)} ={" "}
        <b>{n(r.harvest_tons_per_acre)} US tons/acre</b>
      </p>
      <p>
        Denominator: median modeled relative yield with uncapped water over the
        selected years for this crop and calendar. It stays fixed when your
        water limit changes, rather than normalizing away the yield loss. This
        is a model calibration, not an observed harvest.
      </p>
      <p className="equation">
        {n(r.harvest_tons_per_acre)} tons/acre × {n(block.acres)} acres ={" "}
        <b>{n(r.harvest_tons)} US tons</b>
      </p>
      <p>
        Pounds = US tons × 2,000. These are modeled harvest quantities, not
        farmer harvest records.
      </p>
    </>
  );
  const fin = (
    <>
      <p>
        Price used:{" "}
        <b>
          {n(r.crop_price?.value)} {r.crop_price?.unit}
        </b>
        , source year <b>{r.crop_price?.year ?? "not available"}</b>. This is
        separate from weather/season year {r.year}.
      </p>
      <p>
        Revenue = modeled harvest converted to the price unit × that crop price.
        The harvest conversion uses the same quantity shown in the harvest
        explanation.
      </p>
      <p className="equation">
        {n(r.sale_quantity)}{" "}
        {r.crop_price?.unit.replace(/^\$\s*\/\s*/, "") ?? "sale units"} ×{" "}
        {n(r.crop_price?.value)} {r.crop_price?.unit} ={" "}
        <b>{preciseMoney(r.revenue_unrounded)} sales revenue</b>
      </p>
      <p className="equation">
        Estimated sales {preciseMoney(r.revenue_unrounded)} − estimated cost{" "}
        {preciseMoney(r.cost_unrounded)} ={" "}
        <b>{preciseMoney(r.profit_unrounded)} modeled margin</b>
      </p>
      <p className="equation">
        Regional non-water cost {n(r.production_cost_per_acre)} $/acre ×{" "}
        {n(block.acres)} acres = {preciseMoney(r.production_cost_excl_water)}
      </p>
      <p className="equation">
        Water {n(r.applied_water_unrounded_af)} acre-ft × blended rate{" "}
        {n(r.blended_water_price_per_af)} $/acre-ft ={" "}
        {preciseMoney(r.water_cost)}
      </p>
      <p>
        Blended rate = {n(r.surface_share)} × surface rate{" "}
        {n(r.surface_price_per_af)} + {n(1 - r.surface_share)} × groundwater
        pumping rate.
      </p>
      <p>
        Pumping rate = lift {n(r.pump_lift_ft)} ft × 1.02 kWh/(acre-ft·ft) ÷
        efficiency {n(r.pump_efficiency)} × electricity{" "}
        {n(r.electricity_dollars_per_kwh)} $/kWh. Electricity source year:{" "}
        {r.electricity_price?.year ?? "unavailable"}.
      </p>
      <p>
        Cost study:{" "}
        {r.production_cost_source?.source ??
          "No regional study available. Financial result is unavailable, not zero."}
      </p>
      <p>
        These costs are reference estimates, not your invoices. They are not
        reconstructed historical expenses or adjusted for inflation. Your
        operating budget is a limit; changing it does not replace estimated
        expenses.
      </p>
    </>
  );
  if (metric === "harvest") return h;
  if (["profit", "cost", "revenue"].includes(metric)) return fin;
  if (metric === "water")
    return (
      <>
        <p>
          Gross irrigation = net water applied to the soil ÷ irrigation
          efficiency.
        </p>
        <p className="equation">
          {n(r.net_irrigation_applied_mm)} mm ÷ 304.8 × {n(block.acres)} acres ÷{" "}
          {n(r.irrigation_efficiency)} ={" "}
          <b>{n(r.applied_water_unrounded_af)} acre-ft</b>
        </p>
        <p>
          Net irrigation comes from the daily soil-water balance driven by
          weather, crop coefficients, soil, and any farm water limit. Soil:{" "}
          {r.soil}. This is modeled applied water, not a water-meter reading.
        </p>
      </>
    );
  if (metric === "relative")
    return (
      <>
        <p className="equation">
          Water response = 1 − Ky {n(r.ky)} × (1 − actual crop ET{" "}
          {n(r.eta_active_mm)} ÷ full crop ET {n(r.etc_active_mm)})
        </p>
        <p>
          Subtract heat penalty {n(r.heat_penalty_fraction)} and clip the result
          between 0 and 1. Displayed relative yield:{" "}
          <b>{n(r.displayed.relative_yield * 100)}%</b>.
        </p>
        <p>
          Heat penalty is 0.0025 per heat day above the location's median{" "}
          {n(r.normal_heat_days)} days, capped at 0.10. This heat rule is a team
          assumption, not a validated yield coefficient. The normal uses the
          full available weather record, not only the selected backtest years.
        </p>
      </>
    );
  if (metric === "etc")
    return (
      <>
        <p>
          Daily reference ET0 is calculated from NASA weather with FAO-56
          Penman-Monteith. Daily crop ET = ET0 × that day's crop coefficient.
        </p>
        <p className="equation">
          Sum daily crop ET {n(r.etc_all_mm)} mm ÷ 25.4 ={" "}
          <b>{n(r.displayed.crop_water_use_in)} inches</b> (rounded)
        </p>
        <p>
          Crop coefficients: {JSON.stringify(r.kc)}. Stage lengths:{" "}
          {JSON.stringify(r.stage_days)}. See the linked coefficient record for
          source and verification flags.
        </p>
      </>
    );
  if (metric === "rain")
    return (
      <>
        <p>
          For each day, rain below 5 mm is excluded; 80% of rain at or above 5
          mm enters the modeled effective-rain term. The daily soil balance also
          limits how much water the root zone can retain.
        </p>
        <p className="equation">
          Sum modeled effective rain {n(r.effective_rain_mm)} mm ÷ 25.4 ={" "}
          <b>{n(r.displayed.effective_rain_in)} inches</b> (rounded)
        </p>
      </>
    );
  if (metric === "heat")
    return (
      <p>
        Count active growing days between {r.season_start} and {r.season_end}{" "}
        when NASA daily maximum temperature exceeded{" "}
        <b>{n(r.heat_threshold_c)}°C</b>:{" "}
        <b>{r.displayed.heat_stress_days} days</b>. This is a modeled exposure
        count, not measured crop damage.
      </p>
    );
  if (metric === "gdd")
    return (
      <p>
        For every active growing day, add max(0, (daily Tmax + daily Tmin) ÷ 2 −
        base {n(r.gdd_base_c)}°C). Seasonal sum, rounded:{" "}
        <b>{r.displayed.gdd} °C-days</b>. There is no upper temperature cutoff.
      </p>
    );
  return (
    <>
      {h}
      {fin}
    </>
  );
}
function CalculationPanel({ target, close, result, farm }) {
  const data = result.calculation_details;
  const [year, setYear] = useState(target.year ?? result.years.at(-1));
  const [blockId, setBlockId] = useState(target.blockId ?? "");
  const [metric, setMetric] = useState(target.metric);
  const dialog = useRef(null);
  const previous = useRef(null);
  useEffect(() => {
    previous.current = document.activeElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous.current?.focus();
    };
  }, []);
  const block = data?.blocks.find((b) => b.id === blockId);
  const row = block?.yearly.find((r) => r.year === Number(year));
  const period = periodCalculation(result, metric);
  const totals = data?.annual_totals ?? [];
  const known = totals.filter((r) => r.profit != null);
  const sum = (key) => known.reduce((s, r) => s + r[key], 0);
  return (
    <dialog
      ref={dialog}
      className="calculation-dialog"
      onCancel={close}
      aria-labelledby="calculation-title"
    >
      <div className="calculation-header">
        <div>
          <p className="eyebrow">MODEL INPUTS AND ARITHMETIC</p>
          <h2 id="calculation-title">
            {titles[target.metric] ?? "How was this calculated?"}
          </h2>
        </div>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close calculation"
        >
          <X size={22} />
        </button>
      </div>
      <p>
        {farm.location.label} · {result.years[0]} to {result.years.at(-1)}.
        Results are estimates, not recorded farm outcomes.
      </p>
      {!data ? (
        <p className="error-box">
          This response has no calculation inputs. Rerun in Live backend mode
          after updating the backend. We cannot reconstruct exact sources from
          the displayed number alone.
        </p>
      ) : (
        <>
          <div className="calculation-warning">{data.cost_basis}</div>
          {data.excluded_financial_blocks.length > 0 && (
            <p className="calculation-warning">
              Dollar totals are partial. Excluded entries:{" "}
              {data.excluded_financial_blocks
                .map(
                  (b) =>
                    `${CROPS[b.crop]?.name ?? b.crop} (${b.block_id}; ${b.years.join(", ")})`,
                )
                .join("; ")}
              . Harvest and water totals can include these crops even when money
              totals do not.
            </p>
          )}
          <div className="calculation-controls">
            <label>
              View
              <select
                value={blockId}
                onChange={(e) => setBlockId(e.target.value)}
              >
                <option value="">Whole-period totals</option>
                {data.blocks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {CROPS[b.crop]?.name ?? b.crop} · {b.id}
                  </option>
                ))}
              </select>
            </label>
            {block && (
              <>
                <label>
                  Season year
                  <select
                    value={year}
                    onChange={(e) => setYear(Number(e.target.value))}
                  >
                    {result.years.map((y) => (
                      <option key={y}>{y}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Metric
                  <select
                    value={
                      ["summary", "ranking"].includes(metric)
                        ? "profit"
                        : metric
                    }
                    onChange={(e) => setMetric(e.target.value)}
                  >
                    {Object.entries(titles)
                      .filter(([k]) => !["summary", "ranking"].includes(k))
                      .map(([k, v]) => (
                        <option value={k} key={k}>
                          {v}
                        </option>
                      ))}
                  </select>
                </label>
              </>
            )}
          </div>
          {!block ? (
            <>
              <h3>{period.label}</h3>
              <p className="equation">
                {n(period.sum)} {period.unit} / {period.count} included years ={" "}
                <b>
                  {n(period.average)} {period.unit}/year
                </b>
              </p>
              <h3>Sales minus cost equals modeled margin</h3>
              <p className="equation">
                Average sales {money(data.reconciliation.avg_revenue)} − average
                estimated cost {money(data.reconciliation.avg_cost)} ={" "}
                <b>
                  average modeled margin {money(data.reconciliation.avg_profit)}
                </b>
              </p>
              <p>
                Financial years included: {data.reconciliation.years.join(", ")}
                . Price mode:{" "}
                {data.price_mode === "current"
                  ? "latest available reference prices applied to all weather years"
                  : "historical prices, using nearest available year when missing"}
                .
              </p>
              <p>
                Total profit = sum of the included yearly margins:{" "}
                <b>{money(sum("profit"))}</b>. Average profit = that sum ÷{" "}
                <b>{known.length}</b> included years. Rounded summary values may
                differ by $1.
              </p>
              <p>
                Average harvest = sum of all yearly crop harvest estimates ÷
                number of years. Different crops are combined by weight, not
                economic value. Water = sum across crop entries each year, then
                average across years. Relative yield = sum(acres × crop relative
                yield) ÷ sum(crop-entry acres) per year, then average.
                Successive crop entries can occupy the same land.
              </p>
              <p>
                {result.assumptions.find((a) =>
                  a.includes("years are ranked by"),
                ) ?? "Ranking method is not supplied by the backend."}
              </p>
              <div className="calculation-table">
                <table>
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Harvest (US tons)</th>
                      <th>Sales</th>
                      <th>Cost</th>
                      <th>Margin</th>
                      <th>Water (acre-ft)</th>
                      <th>Relative yield</th>
                    </tr>
                  </thead>
                  <tbody>
                    {totals.map((r) => (
                      <tr key={r.year}>
                        <th>{r.year}</th>
                        <td>
                          {number(
                            periodCalculation(
                              { ...result, years: [r.year] },
                              "harvest",
                            ).sum,
                            2,
                          )}
                        </td>
                        <td>{money(r.revenue)}</td>
                        <td>{money(r.cost)}</td>
                        <td>{money(r.profit)}</td>
                        <td>{number(r.water_applied_af, 1)}</td>
                        <td>{number(100 * r.relative_yield, 2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                Select a crop above for its exact annual calculation, price
                year, and source records.
              </p>
            </>
          ) : (
            <>
              <h3>
                {CROPS[block.crop]?.name ?? block.crop} · {year} · {block.acres}{" "}
                acres
              </h3>
              <p>
                Season dates: {row?.season_start} to {row?.season_end}.
                Cross-year crops are labeled by the year their season ends.
              </p>
              <Equations metric={metric} row={row} block={block} />
              <h3>Sources used for this crop and year</h3>
              {row?.source_warnings?.map((warning) => (
                <p className="calculation-warning" key={warning}>
                  {warning}
                </p>
              ))}
              <Source item={row?.weather_source} />
              <Source item={row?.price_source} />
              <Source item={row?.electricity_source} />
              {block.sources.map((s) => (
                <Source key={s.url} item={s} />
              ))}
              <p>
                Weather processing: {row?.weather_processing.rule} Missing daily
                values before filling:{" "}
                {JSON.stringify(row?.weather_processing.missing_before_fill)}.
              </p>
            </>
          )}
          <p className="caption">{data.rounding_note}</p>
          <p className="caption">{data.validation_status}</p>
          <Source item={data.model_source} />
          <Source item={data.harvest_source} />
          <p className="caption">
            Model/data snapshot: {data.model_revision}. Weather grid:{" "}
            {data.weather_record.grid_cell.join(", ")}; available record{" "}
            {data.weather_record.start} to {data.weather_record.end}. NASA links
            reproduce the query; upstream data may later be revised.
          </p>
          <p>
            <a
              href="https://power.larc.nasa.gov/docs/services/api/temporal/daily/"
              target="_blank"
              rel="noreferrer"
            >
              NASA API documentation
            </a>{" "}
            ·{" "}
            <a
              href="https://quickstats.nass.usda.gov/"
              target="_blank"
              rel="noreferrer"
            >
              USDA NASS publisher
            </a>{" "}
            ·{" "}
            <a
              href="https://www.fao.org/4/x0490e/x0490e00.htm"
              target="_blank"
              rel="noreferrer"
            >
              FAO-56 method
            </a>
          </p>
        </>
      )}
    </dialog>
  );
}
export function CalculationProvider({ result, farm, children }) {
  const [target, setTarget] = useState(null);
  return (
    <Context.Provider value={setTarget}>
      {children}
      {target && (
        <CalculationPanel
          key={JSON.stringify(target)}
          target={target}
          result={result}
          farm={farm}
          close={() => setTarget(null)}
        />
      )}
    </Context.Provider>
  );
}
export function MoneyExplanation({ result }) {
  const d = result.calculation_details;
  if (!d) return null;
  return (
    <div className="money-explanation" role="note">
      <strong>
        Estimated sales {money(d.reconciliation.avg_revenue)} − estimated cost{" "}
        {money(d.reconciliation.avg_cost)} = modeled margin{" "}
        {money(d.reconciliation.avg_profit)} per year{" "}
        <MetricInfo metric="profit" label="average sales, cost and margin" />
      </strong>
      <p>
        Costs use regional reference studies and modeled water, not your farm's
        actual expenses.{" "}
        {d.excluded_financial_blocks.length
          ? `Partial financial totals: ${d.excluded_financial_blocks.map((b) => CROPS[b.crop]?.name ?? b.crop).join(", ")} excluded because financial inputs are missing.`
          : "All crop entries have financial data."}{" "}
        Your budget is a spending limit, not an operating-cost input.
      </p>
    </div>
  );
}
