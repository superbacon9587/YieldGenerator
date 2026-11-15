import { useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ReferenceArea,
  Cell,
} from "recharts";
import {
  ArrowLeft,
  ArrowUpRight,
  Droplets,
  TrendingUp,
  Wallet,
  Download,
  Printer,
  ArrowDown,
  LoaderCircle,
  Info,
  ChevronDown,
} from "lucide-react";
import {
  CROPS,
  MONTHS,
  IRRIGATION,
  mean,
  number,
  money,
  percent,
  summaryMetrics,
  scenarioFarm,
  validateFarm,
} from "../domain.js";
import { simulate } from "../api.js";
import Timeline from "./Timeline.jsx";
import {
  CalculationProvider,
  MetricInfo,
  MoneyExplanation,
} from "../features/provenance/CalculationDetails.jsx";
import YieldWeightChart from "../features/yield/YieldWeightChart.jsx";
import { useYieldUnit } from "../features/yield/YieldUnitContext.jsx";
import { weightByBlock, weightRow } from "../features/yield/yieldData.js";
import {
  formatWeight,
  potentialPercent,
  unitLabel,
} from "../features/yield/yieldUnits.js";
import SummaryCards from "../features/summary/SummaryCards.jsx";
import BudgetBanner from "../features/summary/BudgetBanner.jsx";
import ProductionChart from "../features/summary/ProductionChart.jsx";
import SaveSetup from "../features/compare/SaveSetup.jsx";
import { periodLabel } from "../features/summary/landBudget.js";

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <div className="metric">
      <span className="metric-label">
        {label}
        <Icon size={17} />
      </span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
function download(data) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "yieldgenerator-comparison.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Comparison({ base, result }) {
  const a = summaryMetrics(base),
    b = summaryMetrics(result);
  const rows = [
    ["Applied water / year", "water", (v) => `${number(v, 1)} acre-ft`, false],
    ["Area-weighted relative yield", "yield", percent, true],
    ["Profit / year", "profit", money, true],
    ["Lowest yearly profit", "worstProfit", money, true],
  ];
  return (
    <div className="comparison-table">
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>Original farm</th>
            <th>Changed scenario</th>
            <th>Difference</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key, format, higher]) => {
            const financial = key === "profit" || key === "worstProfit";
            const completeMoney = [base, result].every((response) =>
              response.blocks.every((block) =>
                block.yearly.every((row) => row.profit != null),
              ),
            );
            const delta =
              a[key] == null || b[key] == null || (financial && !completeMoney)
                ? null
                : b[key] - a[key];
            const favorable = delta != null && (higher ? delta > 0 : delta < 0);
            return (
              <tr key={key}>
                <th>{label}</th>
                <td>{format(a[key])}</td>
                <td>{format(b[key])}</td>
                <td
                  className={
                    delta === 0 || delta == null
                      ? ""
                      : favorable
                        ? "positive"
                        : "negative"
                  }
                >
                  {delta == null
                    ? "Not comparable"
                    : key === "yield"
                      ? `${delta > 0 ? "+" : ""}${number(delta * 100, 1)} pp`
                      : `${delta > 0 ? "+" : ""}${key === "profit" || key === "worstProfit" ? money(delta) : `${number(delta, 1)} acre-ft`}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="caption">
        pp = percentage points. Lower applied water is not proof of higher yield
        or an agronomically better choice. Check all metrics, assumptions, and
        installation costs. Financial differences are withheld when any crop
        lacks profit data.
      </p>
    </div>
  );
}

export default function Results({ farm, result, mock, onBack }) {
  const [chart, setChart] = useState("yield"),
    [year, setYear] = useState(result.summary.typical_year ?? result.years[0]);
  const [selected, setSelected] = useState(farm.blocks[0].id),
    [change, setChange] = useState({ ...farm.blocks[0] }),
    [scenario, setScenario] = useState(null),
    [scenarioInput, setScenarioInput] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [scenarioTitle, setScenarioTitle] = useState("");
  const metrics = summaryMetrics(result);
  const { unit: yieldUnit } = useYieldUnit();
  const weights = weightByBlock(result);
  const chartRows = result.years.map((y) => {
    const total = result.farm_totals.find((r) => r.year === y) ?? {};
    return {
      year: y,
      profit: total.profit,
      ...Object.fromEntries(
        result.blocks.map((b) => [
          b.id,
          b.yearly.find((r) => r.year === y)?.water_applied_af ?? null,
        ]),
      ),
    };
  });
  const flagged = result.summary.drought_years ?? [];
  const overBudget = new Set(result.budget?.years_over_budget ?? []);
  const unit =
    chart === "water"
      ? "acre-feet applied"
      : chart === "production"
        ? `Harvest weight per crop entry, in ${unitLabel(yieldUnit, false)}`
        : "USD";
  async function compare(type = "custom", override) {
    setBusy(true);
    setError("");
    try {
      const changed = scenarioFarm(
        farm,
        { type, blockId: selected, ...change, ...override },
        result,
      );
      const errors = validateFarm(changed);
      if (errors.length) throw new Error(errors.join(" "));
      const output = await simulate(changed, { mock });
      setScenario(output);
      setScenarioInput(changed);
      setScenarioTitle(
        type === "water"
          ? "Water budget at 75% of baseline mean use"
          : type === "drip"
            ? "All crop entries switched to drip"
            : `Changed ${CROPS[change.crop]?.name ?? change.crop} scenario`,
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function chooseBlock(id) {
    setSelected(id);
    setChange({ ...farm.blocks.find((b) => b.id === id) });
  }
  return (
    <CalculationProvider result={result} farm={farm}>
      <div className="results">
        <div className="results-toolbar">
          <button className="text-button" onClick={onBack}>
            <ArrowLeft size={15} /> Edit farm
          </button>
          <div>
            <SaveSetup farm={farm} result={result} />
            <button className="secondary" onClick={() => window.print()}>
              <Printer size={15} /> Print
            </button>
            <button
              className="secondary"
              onClick={() =>
                download({
                  mode: mock ? "synthetic_demo" : "backend",
                  request: farm,
                  baseline: result,
                  scenario_request: scenarioInput,
                  scenario,
                })
              }
            >
              <Download size={15} /> Download
            </button>
          </div>
        </div>
        <div className="result-context">
          <MapLabel location={result.location.label} />
          <span className="period-line">{periodLabel(result.years)}</span>
        </div>
        <BudgetBanner result={result} />
        <SummaryCards result={result} />
        <MoneyExplanation result={result} />
        <p className="yield-note">
          <Info size={15} />
          <span>
            Harvest weight starts from the selected county or statewide median
            NASS yield and moves up or down with each year's growing conditions.
            The percent of potential compares against a crop with no water or
            heat stress. The Production tab shows each crop entry's total
            harvest weight.
          </span>
        </p>
        <Timeline blocks={farm.blocks} compact />
        <section className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">THE HISTORICAL PICTURE</span>
              <h2>
                {chart === "yield"
                  ? "How yield changes across years"
                  : chart === "water"
                    ? "Where the water goes"
                    : chart === "production"
                      ? "What each crop produced"
                      : "The economics, year by year"}
              </h2>
            </div>
            <div className="segmented chart-tabs" aria-label="Chart view">
              {["yield", "water", "profit", "production"].map((key) => (
                <button
                  key={key}
                  aria-pressed={chart === key}
                  onClick={() => setChart(key)}
                >
                  {key === "yield"
                    ? "Yield"
                    : key === "water"
                      ? "Water"
                      : key === "profit"
                        ? "Profit"
                        : "Production"}
                </button>
              ))}
            </div>
          </div>
          {chart === "yield" ? (
            <YieldWeightChart result={result} mock={mock} />
          ) : chart === "production" ? (
            <>
              <p className="caption">{unit}</p>
              <ProductionChart result={result} />
            </>
          ) : (
            <>
              <p className="caption">
                {unit} · Shaded years are flagged by the backend, not detected
                by this chart.
                {mock ? " Demo dips are intentionally constructed." : ""}
              </p>
              <div
                className="chart-wrap"
                role="img"
                aria-label={`${chart} chart across ${result.years.length} historical seasons. Exact values are available in the year table below.`}
              >
                <ResponsiveContainer width="100%" height="100%">
                  {
                    <BarChart
                      data={chartRows}
                      margin={{ top: 12, right: 15, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 4"
                        vertical={false}
                        stroke="#e5e9df"
                      />
                      <XAxis
                        dataKey="year"
                        tick={{ fontSize: 11 }}
                        minTickGap={28}
                      />
                      <YAxis
                        tickFormatter={(v) =>
                          chart === "profit"
                            ? `$${number(v / 1000)}k`
                            : number(v)
                        }
                        tick={{ fontSize: 11 }}
                        width={58}
                      />
                      {flagged.map((y) => (
                        <ReferenceArea
                          key={y}
                          x1={y}
                          x2={y + 1}
                          fill="#d7be85"
                          fillOpacity={0.16}
                        />
                      ))}
                      <Tooltip
                        formatter={(v, name) => [
                          chart === "profit"
                            ? money(v)
                            : `${number(v, 1)} acre-ft`,
                          name,
                        ]}
                        contentStyle={tooltipStyle}
                      />
                      <Legend
                        iconType="circle"
                        wrapperStyle={{ fontSize: 12, paddingTop: 20 }}
                      />
                      {chart === "water" ? (
                        result.blocks.map((b) => (
                          <Bar
                            key={b.id}
                            dataKey={b.id}
                            name={`${CROPS[b.crop]?.name ?? b.crop} · ${b.id}`}
                            stackId="water"
                            fill={CROPS[b.crop]?.color ?? "#557f65"}
                            isAnimationActive={false}
                          />
                        ))
                      ) : (
                        <Bar
                          dataKey="profit"
                          name="Farm profit"
                          radius={[3, 3, 0, 0]}
                          isAnimationActive={false}
                        >
                          {chartRows.map((r) => (
                            <Cell
                              key={r.year}
                              fill={r.profit >= 0 ? "#4e795d" : "#bb684f"}
                              stroke={
                                overBudget.has(r.year) ? "#d39a2c" : undefined
                              }
                              strokeWidth={overBudget.has(r.year) ? 3 : 0}
                            />
                          ))}
                        </Bar>
                      )}
                    </BarChart>
                  }
                </ResponsiveContainer>
              </div>
            </>
          )}
          {chart === "profit" && (
            <p className="caption">
              {overBudget.size > 0 &&
                "Amber outline: farm cost was above your budget that year. "}
              Missing profit remains unavailable, not zero. Farm financial
              totals may include only crops with price and cost data; check the
              assumptions.
            </p>
          )}
        </section>
        <section className="panel year-details">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LOOK A LITTLE CLOSER</span>
              <h2>One season, crop by crop</h2>
            </div>
            <label className="inline-label">
              Year
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
              >
                {result.years.map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Crop entry</th>
                  <th>
                    Crop water use
                    <br />
                    (inches)
                  </th>
                  <th>
                    Effective rain
                    <br />
                    (inches)
                  </th>
                  <th>
                    Applied water
                    <br />
                    (acre-ft)
                  </th>
                  <th>
                    Harvest
                    <br />({unitLabel(yieldUnit, true)})
                  </th>
                  <th>
                    Total harvest
                    <br />({unitLabel(yieldUnit, false)})
                  </th>
                  <th>Heat days</th>
                  <th>
                    GDD
                    <br />
                    (°C-days)
                  </th>
                  <th>Profit</th>
                </tr>
              </thead>
              <tbody>
                {result.blocks.map((b) => {
                  const r = b.yearly.find((r) => r.year === Number(year));
                  const w = weightRow(weights.get(b.id), Number(year));
                  const pct = potentialPercent(
                    w?.relative_yield ?? r?.relative_yield,
                  );
                  return (
                    <tr key={b.id}>
                      <th>
                        <span
                          className="crop-dot"
                          style={{ background: CROPS[b.crop]?.color }}
                        />
                        {CROPS[b.crop]?.name ?? b.crop}
                        <small>
                          {b.id} · {number(b.acres, 1)} acres
                        </small>
                      </th>
                      <td>
                        {number(r?.crop_water_use_in, 1)}
                        <MetricInfo
                          metric="etc"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {number(r?.effective_rain_in, 1)}
                        <MetricInfo
                          metric="rain"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {number(r?.water_applied_af, 1)}
                        <MetricInfo
                          metric="water"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {formatWeight(w?.tons_per_acre, yieldUnit, true)}
                        <MetricInfo
                          metric="harvest_per_acre"
                          blockId={b.id}
                          year={Number(year)}
                        />
                        {pct && (
                          <small className="potential">
                            {pct} of potential
                            <MetricInfo
                              metric="relative"
                              blockId={b.id}
                              year={Number(year)}
                            />
                          </small>
                        )}
                      </td>
                      <td>
                        {formatWeight(w?.tons, yieldUnit, false)}
                        <MetricInfo
                          metric="harvest"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {number(r?.heat_stress_days)}
                        <MetricInfo
                          metric="heat"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {number(r?.gdd)}
                        <MetricInfo
                          metric="gdd"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                      <td>
                        {money(r?.profit)}
                        <MetricInfo
                          metric="profit"
                          blockId={b.id}
                          year={Number(year)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="caption">
            GDD measures accumulated growing warmth. Heat days depend on the
            crop thresholds in the backend.
          </p>
        </section>
        <section className="panel what-if" id="what-if">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">
                KEEP THE FARM. CHANGE A POSSIBILITY.
              </span>
              <h2>What if things were different?</h2>
            </div>
            <span className="scenario-symbol">↗</span>
          </div>
          <p className="subtle">
            Compare against your original farm, using the same location and
            historical years. Results below never overwrite the baseline above.
          </p>
          <div className="quick-actions">
            <button
              className="secondary"
              disabled={busy}
              onClick={() => compare("water")}
            >
              <ArrowDown size={15} /> Cut water budget 25%
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => compare("drip")}
            >
              <Droplets size={15} /> Compare all-drip irrigation
            </button>
          </div>
          <p className="caption">
            The water cut sets the budget to 75% of the baseline mean applied
            water. Drip compatibility and installation costs are not assessed.
          </p>
          <details className="disclosure" open>
            <summary>
              Compare a crop, area, irrigation, or growing-window change
            </summary>
            <div className="scenario-form">
              <label>
                Crop entry
                <select
                  value={selected}
                  onChange={(e) => chooseBlock(e.target.value)}
                >
                  {farm.blocks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {CROPS[b.crop]?.name ?? b.crop} · {b.id}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Try this crop
                <select
                  value={change.crop}
                  onChange={(e) =>
                    setChange({
                      ...change,
                      crop: e.target.value,
                      ...(CROPS[e.target.value]?.perennial
                        ? { start_month: 1, end_month: 12 }
                        : {}),
                    })
                  }
                >
                  {Object.entries(CROPS).map(([key, c]) => (
                    <option key={key} value={key}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Area (acres)
                <input
                  type="number"
                  min="0.0001"
                  step="any"
                  value={change.acres}
                  onChange={(e) =>
                    setChange({ ...change, acres: e.target.value })
                  }
                />
              </label>
              <label>
                Irrigation
                <select
                  value={change.irrigation}
                  onChange={(e) =>
                    setChange({ ...change, irrigation: e.target.value })
                  }
                >
                  {Object.entries(IRRIGATION).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              {["start_month", "end_month"].map((field) => (
                <label key={field}>
                  {field === "start_month" ? "Start month" : "End month"}
                  <select
                    value={change[field]}
                    disabled={CROPS[change.crop]?.perennial}
                    onChange={(e) =>
                      setChange({ ...change, [field]: Number(e.target.value) })
                    }
                  >
                    {MONTHS.map((month, index) => (
                      <option key={month} value={index + 1}>
                        {month}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <p className="caption">
              Annual crop swaps keep the selected growing months. Perennial
              swaps use January to December. Calendar fit, soil, pests,
              equipment, and local markets still need review.
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() => compare()}
            >
              {busy ? (
                <>
                  <LoaderCircle size={16} className="spin" /> Comparing...
                </>
              ) : (
                <>
                  Compare scenario
                  <ArrowUpRight size={16} />
                </>
              )}
            </button>
          </details>
          {error && (
            <p className="error-box" role="alert">
              {error}
            </p>
          )}
          {busy && (
            <p className="caption" role="status">
              Running the changed farm through{" "}
              {mock ? "the demo fixture" : "the backend"}...
            </p>
          )}
          {scenario && (
            <div className="scenario-results" aria-live="polite">
              <span className="eyebrow">
                {mock ? "DEMO COMPARISON" : "MODEL COMPARISON"}
              </span>
              <h3>{scenarioTitle}</h3>
              <Comparison base={result} result={scenario} />
              <CalculationProvider result={scenario} farm={scenarioInput}>
                <MetricInfo metric="summary" label="this what-if scenario" />
              </CalculationProvider>
              <details className="disclosure">
                <summary>Changed-scenario assumptions</summary>
                <ul className="assumptions">
                  {scenario.assumptions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </section>
        <section className="panel assumption-panel">
          <details>
            <summary>
              <Info size={18} />
              <div>
                <strong>Why these results?</strong>
                <span>Model assumptions, data coverage, and limitations</span>
              </div>
              <ChevronDown size={18} />
            </summary>
            <div className="optional-content">
              <p className="subtle">
                {mock
                  ? "Demo coordinates (not a measured NASA grid cell)"
                  : "NASA POWER grid cell"}
                : {result.location.grid_cell?.join(", ") ?? "Not supplied"}.
                Regional weather does not capture every field's conditions.
              </p>
              <ul className="assumptions">
                {result.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
              <p className="caption">
                Historical model outputs are not a future yield guarantee. These
                scenarios support local review, not automatic crop or irrigation
                prescriptions.
              </p>
            </div>
          </details>
        </section>
      </div>
    </CalculationProvider>
  );
}
const tooltipStyle = {
  border: "1px solid #dce3d6",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 10px 25px #1c3d3010",
};
function MapLabel({ location }) {
  return (
    <strong>
      <span className="location-dot" />
      {location || "Selected farm"}
    </strong>
  );
}
