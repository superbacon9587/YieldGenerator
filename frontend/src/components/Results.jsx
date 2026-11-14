import { useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
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
  Lightbulb,
  ArrowDown,
  LoaderCircle,
  Info,
  ChevronDown,
} from "lucide-react";
import {
  CROPS,
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
  const flags = [...(result.waste_flags ?? [])].sort(
    (a, b) =>
      (b.estimated_cost_per_year ?? -Infinity) -
      (a.estimated_cost_per_year ?? -Infinity),
  );
  const chartRows = result.years.map((y) => {
    const total = result.farm_totals.find((r) => r.year === y) ?? {};
    return {
      year: y,
      profit: total.profit,
      ...Object.fromEntries(
        result.blocks.map((b) => [
          b.id,
          chart === "yield"
            ? (b.yearly.find((r) => r.year === y)?.relative_yield ?? null) ==
              null
              ? null
              : b.yearly.find((r) => r.year === y).relative_yield * 100
            : (b.yearly.find((r) => r.year === y)?.water_applied_af ?? null),
        ]),
      ),
    };
  });
  const flagged = result.summary.drought_years ?? [];
  const unit =
    chart === "yield"
      ? "% of unstressed baseline"
      : chart === "water"
        ? "acre-feet applied"
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
    <div className="results">
      <div className="results-toolbar">
        <button className="text-button" onClick={onBack}>
          <ArrowLeft size={15} /> Edit farm
        </button>
        <div>
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
        <span>
          {result.years[0]} to {result.years.at(-1)} · {result.years.length}{" "}
          historical seasons
        </span>
      </div>
      <div className="metrics-grid">
        <Metric
          label="Relative yield"
          value={percent(metrics.yield)}
          detail="Mean of yearly area-weighted fractions"
          icon={TrendingUp}
        />
        <Metric
          label="Water applied / year"
          value={`${number(metrics.water, 1)}`}
          detail="acre-feet, historical mean"
          icon={Droplets}
        />
        <Metric
          label="Profit / year"
          value={money(metrics.profit)}
          detail="Mean of available financial results"
          icon={Wallet}
        />
        <div className="metric year-metric">
          <span className="metric-label">
            Historical comparison
            <TrendingUp size={17} />
          </span>
          <div>
            <span>
              <small>Best year</small>
              <strong>{result.summary.best_year ?? "Not available"}</strong>
            </span>
            <span>
              <small>Worst year</small>
              <strong>{result.summary.worst_year ?? "Not available"}</strong>
            </span>
          </div>
          <small>Ranking method is listed in assumptions</small>
        </div>
      </div>
      <p className="yield-note">
        <Info size={15} />
        <span>
          Relative yield compares against the model's unstressed baseline. It is
          not tonnes or pounds harvested. Absolute harvest estimates require
          baseline yields and units that this API does not currently return.
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
                  : "The economics, year by year"}
            </h2>
          </div>
          <div className="segmented chart-tabs" aria-label="Chart view">
            {["yield", "water", "profit"].map((key) => (
              <button
                key={key}
                aria-pressed={chart === key}
                onClick={() => setChart(key)}
              >
                {key === "yield"
                  ? "Yield"
                  : key === "water"
                    ? "Water"
                    : "Profit"}
              </button>
            ))}
          </div>
        </div>
        <p className="caption">
          {unit} · Shaded years are flagged by the backend, not detected by this
          chart.{mock ? " Demo dips are intentionally constructed." : ""}
        </p>
        <div
          className="chart-wrap"
          role="img"
          aria-label={`${chart} chart across ${result.years.length} historical seasons. Exact values are available in the year table below.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            {chart === "yield" ? (
              <LineChart
                data={chartRows}
                margin={{ top: 12, right: 15, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 4"
                  vertical={false}
                  stroke="#e5e9df"
                />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} minTickGap={28} />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  tick={{ fontSize: 11 }}
                  width={48}
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
                  formatter={(v, name) => [`${number(v, 1)}%`, name]}
                  contentStyle={tooltipStyle}
                />
                <Legend
                  iconType="circle"
                  wrapperStyle={{ fontSize: 12, paddingTop: 20 }}
                />
                {result.blocks.map((b) => (
                  <Line
                    key={b.id}
                    dataKey={b.id}
                    name={`${CROPS[b.crop]?.name ?? b.crop} · ${b.id}`}
                    stroke={CROPS[b.crop]?.color ?? "#557f65"}
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5 }}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            ) : (
              <BarChart
                data={chartRows}
                margin={{ top: 12, right: 15, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 4"
                  vertical={false}
                  stroke="#e5e9df"
                />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} minTickGap={28} />
                <YAxis
                  tickFormatter={(v) =>
                    chart === "profit" ? `$${number(v / 1000)}k` : number(v)
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
                    chart === "profit" ? money(v) : `${number(v, 1)} acre-ft`,
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
                      />
                    ))}
                  </Bar>
                )}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
        {chart === "profit" && (
          <p className="caption">
            Missing profit remains unavailable, not zero. Farm financial totals
            may include only crops with price and cost data; check the
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
                <th>Relative yield</th>
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
                    <td>{number(r?.crop_water_use_in, 1)}</td>
                    <td>{number(r?.effective_rain_in, 1)}</td>
                    <td>{number(r?.water_applied_af, 1)}</td>
                    <td>{percent(r?.relative_yield)}</td>
                    <td>{number(r?.heat_stress_days)}</td>
                    <td>{number(r?.gdd)}</td>
                    <td>{money(r?.profit)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="caption">
          GDD measures accumulated growing warmth. Heat days depend on the crop
          thresholds in the backend.
        </p>
      </section>
      <section className="panel opportunities">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">POSSIBILITIES, NOT PRESCRIPTIONS</span>
            <h2>
              <Lightbulb size={20} /> What could you explore?
            </h2>
          </div>
          <span className="chip">{flags.length} model flags</span>
        </div>
        <p className="subtle">
          Use a flag to start a comparison. Estimated losses are not measured
          waste, and a different crop is not automatically suitable.
        </p>
        {flags.length ? (
          flags.map((flag, i) => (
            <div className="flag" key={`${flag.block_id}-${i}`}>
              <div className="flag-icon">
                <Droplets size={19} />
              </div>
              <div>
                <strong>
                  {flag.block_id === "farm"
                    ? "Farm-wide check"
                    : `${CROPS[result.blocks.find((b) => b.id === flag.block_id)?.crop]?.name ?? flag.block_id} · ${flag.block_id}`}
                </strong>
                <p>{flag.message}</p>
                <small>
                  {number(flag.estimated_af_per_year, 1)} acre-ft / year ·{" "}
                  {flag.estimated_cost_per_year == null
                    ? "Cost unavailable"
                    : `${money(flag.estimated_cost_per_year)} / year`}{" "}
                  {mock ? "· synthetic estimate" : "· modeled estimate"}
                </small>
                {farm.blocks.some((b) => b.id === flag.block_id) && (
                  <div className="goal-action">
                    <button
                      className="text-button"
                      onClick={() => {
                        chooseBlock(flag.block_id);
                        document
                          .getElementById("what-if")
                          ?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                      }}
                    >
                      Explore this crop entry <ArrowUpRight size={13} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="empty-inline">
            No flags returned. This does not establish that the farm is optimal.
          </div>
        )}
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
          <summary>Compare a crop, area, or irrigation change</summary>
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
                onChange={(e) => setChange({ ...change, crop: e.target.value })}
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
          </div>
          <p className="caption">
            Annual crop swaps keep the selected growing months. Perennial swaps
            use January to December. Calendar fit, soil, pests, equipment, and
            local markets still need review.
          </p>
          <button className="primary" disabled={busy} onClick={() => compare()}>
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
