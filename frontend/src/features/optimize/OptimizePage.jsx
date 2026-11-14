import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronDown,
  Info,
  LoaderCircle,
  Target,
  TreeDeciduous,
} from "lucide-react";
import { CROPS, IRRIGATION, money, number } from "../../domain.js";
import PlanCard from "./PlanCard.jsx";
import {
  BUDGET_RULES,
  OBJECTIVES,
  buildRequest,
  differenceCells,
  farmErrors,
  findBlockers,
  inputHint,
  planToFarm,
  settingsOf,
} from "./optimizePlan.js";
import { optimize } from "./optimizeApi.js";
import "../compare/compare.css";
import "./optimize.css";

const signed = (v, format) => (v == null ? "Not available" : `${v > 0 ? "+" : v < 0 ? "-" : ""}${format(Math.abs(v))}`);
const DIFF_FORMAT = {
  avg_profit: (v) => money(v),
  avg_yield_tons: (v) => `${number(v, v >= 100 ? 0 : 1)} tons`,
  avg_water_applied_af: (v) => `${number(v, 1)} acre-ft`,
  avg_cost: (v) => money(v),
};

function Inputs({ farm, setFarm }) {
  const s = settingsOf(farm);
  const setSetting = (patch) => setFarm({ ...farm, optimize: { ...s, ...patch } });
  const setOptional = (key, value) => setFarm({ ...farm, optional: { ...farm.optional, [key]: value } });
  const toggle = (key, value) =>
    setSetting({
      [key]: s[key].includes(value) ? s[key].filter((x) => x !== value) : [...s[key], value],
    });
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">REQUIRED</span>
            <h2>Land and budget</h2>
          </div>
          <span className="chip">Shared with Your farm</span>
        </div>
        <div className="form-grid two">
          <label>
            Available acreage
            <input
              type="number"
              min="0.1"
              step="any"
              required
              value={farm.available_acres ?? ""}
              onChange={(e) => setFarm({ ...farm, available_acres: e.target.value })}
            />
          </label>
          <label>
            Yearly operating budget ($)
            <input
              type="number"
              min="0"
              step="any"
              required
              value={farm.optional.budget_usd ?? ""}
              onChange={(e) => setOptional("budget_usd", e.target.value)}
            />
          </label>
        </div>
        <fieldset className="price-mode">
          <legend>Budget rule</legend>
          <div className="segmented">
            {Object.entries(BUDGET_RULES).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={s.budget_rule === key}
                onClick={() => setSetting({ budget_rule: key })}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">OPTIONAL</span>
            <h2>Limits and choices</h2>
          </div>
        </div>
        <div className="form-grid two">
          <label>
            Water available per year (acre-ft)
            <input
              type="number"
              min="0"
              step="any"
              placeholder="No limit"
              value={farm.optional.water_available_af ?? ""}
              onChange={(e) => setOptional("water_available_af", e.target.value)}
            />
          </label>
          <label>
            Minimum block size (acres)
            <input
              type="number"
              min="0"
              step="any"
              value={s.min_block_acres}
              onChange={(e) => setSetting({ min_block_acres: e.target.value })}
            />
          </label>
        </div>
        <label className="opt-slider">
          Max share for any one crop: <b>{Math.round(Number(s.max_share_per_crop) * 100)}%</b>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.05"
            value={s.max_share_per_crop}
            onChange={(e) => setSetting({ max_share_per_crop: Number(e.target.value) })}
          />
        </label>
        <div className="opt-checks">
          <fieldset>
            <legend>Allowed crops</legend>
            {Object.entries(CROPS).map(([key, crop]) => (
              <label key={key} className="opt-check">
                <input
                  type="checkbox"
                  checked={s.allowed_crops.includes(key)}
                  onChange={() => toggle("allowed_crops", key)}
                />
                <i style={{ background: crop.color }} aria-hidden="true" />
                {crop.name}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>Allowed irrigation</legend>
            {Object.entries(IRRIGATION).map(([key, label]) => (
              <label key={key} className="opt-check">
                <input
                  type="checkbox"
                  checked={s.allowed_irrigation.includes(key)}
                  onChange={() => toggle("allowed_irrigation", key)}
                />
                {label}
              </label>
            ))}
          </fieldset>
        </div>
        <label className="opt-toggle">
          <input
            type="checkbox"
            role="switch"
            checked={Boolean(s.allow_new_perennials)}
            onChange={(e) => setSetting({ allow_new_perennials: e.target.checked })}
          />
          <span className="opt-switch" aria-hidden="true" />
          <span>
            <strong>
              <TreeDeciduous size={14} /> Allow new orchards
            </strong>
            <small>
              New orchards take years to bear, and establishment costs are not included. When this is
              off, orchards and alfalfa on your current farm keep their acres.
            </small>
          </span>
        </label>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">OBJECTIVE</span>
            <h2>What the plan maximizes</h2>
          </div>
          <Target size={20} className="muted-icon" />
        </div>
        <div className="opt-objectives" role="radiogroup" aria-label="Objective">
          {Object.entries(OBJECTIVES).map(([key, o]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={s.objective === key}
              className={`opt-objective ${s.objective === key ? "selected" : ""}`}
              onClick={() => setSetting({ objective: key })}
            >
              <strong>{o.title}</strong>
              <span>{o.blurb}</span>
              {o.note && <small>{o.note}</small>}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}

function Difference({ diff }) {
  return (
    <div className="opt-diff" aria-label="Plan minus current farm">
      <span className="opt-diff-title">Plan minus current farm, per year</span>
      {differenceCells(diff).map((c) => (
        <div key={c.key} className={c.tone}>
          <span>{c.label}</span>
          <strong>{signed(c.value, DIFF_FORMAT[c.key])}</strong>
        </div>
      ))}
    </div>
  );
}

function NoPlan({ result }) {
  const title = {
    infeasible: "No plan fits these limits",
    no_profitable_plan: "No plan earns a profit with these inputs",
    error: "The plan did not pass the backtest check",
  }[result.status];
  return (
    <section className="panel opt-noplan" role="alert">
      <AlertTriangle size={22} />
      <div>
        <h2>{title}</h2>
        {result.status === "error" ? (
          <>
            <p>
              The optimizer found a plan, but rerunning it through the full backtest gave different
              numbers or broke a limit, so it is not shown.
            </p>
            <p className="caption">{result.error_detail}</p>
          </>
        ) : (
          <>
            <p>{result.infeasible_reason}</p>
            <p className="opt-hint">{inputHint(result.status, result.infeasible_reason ?? "")}</p>
          </>
        )}
      </div>
    </section>
  );
}

function Results({ result, farm, mock, onBacktest }) {
  const objective = OBJECTIVES[result.objective] ?? OBJECTIVES.profit;
  const hasPlan = ["optimal", "feasible"].includes(result.status);
  return (
    <div aria-live="polite">
      {hasPlan ? (
        <>
          {result.status === "feasible" && (
            <p className="opt-note">
              <Info size={15} /> The search reached its time limit. This is the highest scoring plan
              found in that time.
            </p>
          )}
          <div className="opt-side">
            {result.current_farm && (
              <PlanCard
                eyebrow="TODAY"
                title="Your current farm"
                part={result.current_farm}
                tone="current"
              />
            )}
            <PlanCard
              eyebrow={mock ? "DEMO PLAN" : "OPTIMIZED"}
              title={objective.plan}
              part={result.plan}
              farm={planToFarm(farm, result.plan.blocks)}
              onBacktest={onBacktest}
              tone="plan"
            />
          </div>
          {result.difference_vs_current && <Difference diff={result.difference_vs_current} />}
          <section className="panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">BINDING LIMITS</span>
                <h2>What limits this plan</h2>
              </div>
              <span className="chip">{result.options_considered} options compared</span>
            </div>
            {result.binding_constraints.length ? (
              <ul className="opt-limits">
                {result.binding_constraints.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            ) : (
              <p className="subtle">No limit is fully used by this plan.</p>
            )}
          </section>
          {result.alternatives.length > 0 && (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">OTHER PLANS</span>
                  <h2>Alternatives</h2>
                </div>
              </div>
              <p className="subtle">
                Each alternative uses a different set of crop, irrigation, and planting month choices.
              </p>
              <div className="opt-alts">
                {result.alternatives.map((a) => (
                  <PlanCard
                    key={a.label}
                    eyebrow="ALTERNATIVE"
                    title={a.label}
                    part={a}
                    farm={planToFarm(farm, a.blocks)}
                    onBacktest={onBacktest}
                    compact
                  />
                ))}
              </div>
            </section>
          )}
        </>
      ) : (
        <NoPlan result={result} />
      )}
      <section className="panel assumption-panel">
        <details>
          <summary>
            <Info size={18} />
            <div>
              <strong>Assumptions behind this plan</strong>
              <span>{result.assumptions.length} notes on data, limits, and what is not included</span>
            </div>
            <ChevronDown size={18} />
          </summary>
          <div className="optional-content">
            <ul className="assumptions">
              {result.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        </details>
      </section>
    </div>
  );
}

/** "Optimize": inputs, objective, Find plan, and the plan next to the current farm. */
export default function OptimizePage({ farm, setFarm, mock, onBacktest }) {
  const [busy, setBusy] = useState(false),
    [seconds, setSeconds] = useState(0),
    [error, setError] = useState(""),
    [result, setResult] = useState(null),
    [ranFor, setRanFor] = useState(null);
  const timer = useRef(null);
  useEffect(() => () => clearInterval(timer.current), []);

  const blockers = findBlockers(farm);
  async function find() {
    const errors = farmErrors(farm);
    if (errors.length) {
      setError(`Check Your farm first: ${errors.join(" ")}`);
      return;
    }
    setBusy(true);
    setError("");
    setSeconds(0);
    const started = Date.now();
    timer.current = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 500);
    try {
      const response = await optimize(buildRequest(farm), { mock });
      setResult(response);
      setRanFor(farm);
    } catch (e) {
      setError(e.message);
    } finally {
      clearInterval(timer.current);
      setBusy(false);
    }
  }

  return (
    <div className="optimize-page">
      <Inputs farm={farm} setFarm={setFarm} />
      <div className="opt-find">
        <button className="primary" disabled={busy || blockers.length > 0} onClick={find}>
          {busy ? (
            <>
              <LoaderCircle size={16} className="spin" /> Finding plan... {seconds}s
            </>
          ) : (
            <>
              Find plan <ArrowUpRight size={16} />
            </>
          )}
        </button>
        <span className="caption" role="status">
          {busy
            ? "Running every option through the backtest engine, then checking the plan."
            : blockers.length
              ? blockers.join(" ")
              : `Uses ${farm.location.label || "your location"}, ${farm.years[0]} to ${farm.years[1]}, and your current crops from Your farm.`}
        </span>
      </div>
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {result && !busy && (
        <Results result={result} farm={ranFor ?? farm} mock={mock} onBacktest={onBacktest} />
      )}
    </div>
  );
}
