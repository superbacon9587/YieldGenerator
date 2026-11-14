import { useState } from "react";
import { ArrowUpRight, LoaderCircle, Trash2, Upload } from "lucide-react";
import { money, number, percent } from "../../domain.js";
import { compareSetups } from "../../api.js";
import {
  LOWER_IS_FIRST,
  MAX_COMPARE,
  MIN_COMPARE,
  RANK_OPTIONS,
  bestValue,
  loadSetups,
  persistSetups,
  removeSetup,
  setupAcres,
  setupCrops,
} from "./savedSetups.js";
import "./compare.css";

const COLUMNS = [
  ["total_profit", "Total profit", money, false],
  ["avg_profit", "Average profit", money, false],
  ["avg_relative_yield", "Average relative yield", percent, false],
  ["avg_water_applied_af", "Average water", (v) => (v == null ? "Not available" : `${number(v, 1)} acre-ft`), true],
];

const savedDate = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

function RankingTable({ data }) {
  const rows = data.results;
  const best = Object.fromEntries(
    COLUMNS.map(([key, , , lower]) => [
      key,
      bestValue(rows.map((r) => r.summary_stats?.[key]), lower),
    ]),
  );
  const overCounts = rows.map((r) => r.budget?.years_over_budget?.length ?? null);
  const bestOver = bestValue(
    rows.filter((r) => r.budget?.budget_usd != null).map((r) => r.budget.years_over_budget.length),
    true,
  );
  return (
    <div className="comparison-table compare-table">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Setup</th>
            {COLUMNS.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
            <th>Years over budget</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.name}>
              <td className="compare-rank">{r.rank}</td>
              <th>{r.name}</th>
              {COLUMNS.map(([key, , format]) => {
                const v = r.summary_stats?.[key];
                return (
                  <td key={key} className={v != null && v === best[key] ? "compare-best" : ""}>
                    {format(v)}
                  </td>
                );
              })}
              <td
                className={
                  r.budget?.budget_usd != null && overCounts[i] === bestOver ? "compare-best" : ""
                }
              >
                {r.budget?.budget_usd == null
                  ? "No budget set"
                  : `${overCounts[i]} of ${r.summary_stats?.years_count ?? "?"}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">
        Bold marks the highest value in each column, or the lowest for water and
        years over budget. Profit only adds up crops with price data.
      </p>
    </div>
  );
}

/** "Compare setups": saved setups as cards, pick 2 to 6, rank them. */
export default function ComparePage({ mock, onLoad }) {
  const [setups, setSetups] = useState(() => loadSetups()),
    [picked, setPicked] = useState([]),
    [rankedBy, setRankedBy] = useState("avg_profit"),
    [data, setData] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");

  function toggle(name) {
    setPicked((p) =>
      p.includes(name) ? p.filter((n) => n !== name) : p.length >= MAX_COMPARE ? p : [...p, name],
    );
  }
  function remove(name) {
    const next = removeSetup(setups, name);
    persistSetups(next);
    setSetups(next);
    setPicked((p) => p.filter((n) => n !== name));
    setData(null);
  }
  async function run(by = rankedBy) {
    setBusy(true);
    setError("");
    try {
      const configs = setups
        .filter((s) => picked.includes(s.name))
        .map((s) => ({ name: s.name, farm: s.farm }));
      setData(await compareSetups(configs, by, { mock }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const ready = picked.length >= MIN_COMPARE && picked.length <= MAX_COMPARE;

  return (
    <div className="compare-page">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">SAVED ON THIS DEVICE</span>
            <h2>Your saved setups</h2>
          </div>
          <span className="chip">{setups.length} saved</span>
        </div>
        {setups.length ? (
          <>
            <p className="subtle">
              Pick {MIN_COMPARE} to {MAX_COMPARE} setups to rank them side by side. Load
              puts a setup back into Your farm.
            </p>
            <div className="setup-cards">
              {setups.map((s) => {
                const on = picked.includes(s.name);
                return (
                  <article className={`setup-card ${on ? "picked" : ""}`} key={s.name}>
                    <label className="setup-pick">
                      <input
                        type="checkbox"
                        checked={on}
                        disabled={!on && picked.length >= MAX_COMPARE}
                        onChange={() => toggle(s.name)}
                      />
                      <strong>{s.name}</strong>
                    </label>
                    <p>{setupCrops(s.farm)}</p>
                    <small>
                      {number(setupAcres(s.farm), 1)} acres · saved {savedDate(s.saved_at)}
                    </small>
                    <div className="setup-actions">
                      <button className="text-button" onClick={() => onLoad(s.farm)}>
                        <Upload size={13} /> Load
                      </button>
                      <button
                        className="text-button danger"
                        onClick={() => remove(s.name)}
                        aria-label={`Delete ${s.name}`}
                      >
                        <Trash2 size={13} /> Delete
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="compare-controls">
              <button className="primary" disabled={!ready || busy} onClick={() => run()}>
                {busy ? (
                  <>
                    <LoaderCircle size={16} className="spin" /> Comparing...
                  </>
                ) : (
                  <>
                    Compare {picked.length || ""} setups <ArrowUpRight size={16} />
                  </>
                )}
              </button>
              <label className="inline-label">
                Rank by
                <select
                  value={rankedBy}
                  onChange={(e) => {
                    setRankedBy(e.target.value);
                    if (data && ready) run(e.target.value);
                  }}
                >
                  {Object.entries(RANK_OPTIONS).map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                      {LOWER_IS_FIRST.has(k) ? " (lowest first)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              {!ready && (
                <span className="caption">
                  Select {MIN_COMPARE} to {MAX_COMPARE} setups.
                </span>
              )}
            </div>
          </>
        ) : (
          <div className="empty-inline">
            No saved setups yet. Run a backtest, then use "Save this setup" on the results
            page.
          </div>
        )}
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
      </section>
      {data && (
        <section className="panel" aria-live="polite">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">{mock ? "DEMO RANKING" : "MODEL RANKING"}</span>
              <h2>Ranked by {RANK_OPTIONS[data.ranked_by].toLowerCase()}</h2>
            </div>
          </div>
          <RankingTable data={data} />
        </section>
      )}
    </div>
  );
}
