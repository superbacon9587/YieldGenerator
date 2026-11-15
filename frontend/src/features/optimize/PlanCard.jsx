import { useState } from "react";
import { Bookmark, Check, Play } from "lucide-react";
import { CROPS, IRRIGATION, MONTHS, activeMonth, money, number } from "../../domain.js";
import { addSetup, loadSetups, persistSetups } from "../compare/savedSetups.js";
import { monthsLabel, tonsByCrop } from "./optimizePlan.js";
import { CalcInfo, CalcRecords } from "../provenance/CalcPopover.jsx";

const tons = (v) => (v == null ? "No yield data" : `${number(v, v >= 100 ? 0 : 1)} tons`);
const acreFeet = (v) => (v == null ? "Not available" : `${number(v, 1)} acre-ft`);

/** 12-month strip per block, in the shared crop colors. */
export function MiniCalendar({ blocks }) {
  return (
    <div className="opt-calendar" role="img" aria-label="Crop calendar for this plan">
      <div className="opt-calendar-row opt-calendar-head" aria-hidden="true">
        <span />
        {MONTHS.map((m) => (
          <span key={m}>{m[0]}</span>
        ))}
      </div>
      {blocks.map((b) => (
        <div className="opt-calendar-row" key={b.id}>
          <span className="opt-calendar-name">
            <i style={{ background: CROPS[b.crop]?.color }} />
            {CROPS[b.crop]?.name ?? b.crop}
          </span>
          {MONTHS.map((m, i) => {
            const on = activeMonth(i + 1, Number(b.start_month), Number(b.end_month));
            return (
              <span
                key={m}
                className={`opt-month ${on ? "on" : ""}`}
                style={on ? { background: CROPS[b.crop]?.color } : undefined}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

function BlockList({ blocks }) {
  return (
    <ul className="opt-blocks">
      {blocks.map((b) => (
        <li key={b.id}>
          <i style={{ background: CROPS[b.crop]?.color }} aria-hidden="true" />
          <div>
            <strong>
              {CROPS[b.crop]?.name ?? b.crop} · {number(b.acres, 1)} acres
            </strong>
            <small>
              {IRRIGATION[b.irrigation] ?? b.irrigation} · {monthsLabel(b.start_month, b.end_month)}
            </small>
          </div>
          <div className="opt-block-numbers">
            <span>
              {b.avg_profit == null ? "No price data" : `${money(b.avg_profit)} / yr`}
              <CalcInfo id={`block.${b.id}.avg_profit`} display={money(b.avg_profit)} />
            </span>
            <small>
              {tons(b.avg_yield_tons)} / yr
              <CalcInfo id={`block.${b.id}.avg_yield_tons`} display={tons(b.avg_yield_tons)} weightUnit="tons" />
            </small>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Stats({ stats, blocks, compact = false }) {
  const perCrop = tonsByCrop(blocks);
  return (
    <div className={`opt-stats ${compact ? "opt-compact" : ""}`}>
      <div>
        <span>
          Average profit
          <CalcInfo id="summary.avg_profit" display={money(stats?.avg_profit)} weightUnit="tons" />
        </span>
        <strong>{money(stats?.avg_profit)}</strong>
        <small>per year</small>
      </div>
      <div>
        <span>
          Average harvest
          <CalcInfo id="summary.avg_yield_tons" display={tons(stats?.avg_yield_tons)} weightUnit="tons" />
        </span>
        <strong>{tons(stats?.avg_yield_tons)}</strong>
        <small>
          {perCrop.length
            ? perCrop.map(([c, t]) => `${CROPS[c]?.name ?? c} ${number(t, t >= 100 ? 0 : 1)}`).join(" · ")
            : "per year"}
        </small>
      </div>
      <div>
        <span>
          Average water
          <CalcInfo id="summary.avg_water_applied_af" display={acreFeet(stats?.avg_water_applied_af)} weightUnit="tons" />
        </span>
        <strong>{acreFeet(stats?.avg_water_applied_af)}</strong>
        <small>applied per year</small>
      </div>
      <div>
        <span>
          Average cost
          <CalcInfo id="summary.avg_cost" display={money(stats?.avg_cost)} weightUnit="tons" />
        </span>
        <strong>{money(stats?.avg_cost)}</strong>
        <small>per year</small>
      </div>
    </div>
  );
}

function SavePlan({ farm, stats, defaultName }) {
  const [open, setOpen] = useState(false),
    [name, setName] = useState(defaultName),
    [status, setStatus] = useState("");
  function save(e) {
    e.preventDefault();
    const clean = name.trim();
    if (!clean) {
      setStatus("Enter a name for this setup.");
      return;
    }
    const existing = loadSetups();
    const replaced = existing.some((s) => s.name === clean);
    const ok = persistSetups(addSetup(existing, { name: clean, farm, summary_stats: stats ?? null }));
    setStatus(
      ok
        ? `${replaced ? "Updated" : "Saved"} "${clean}". It is listed in Compare setups.`
        : "This browser could not save setups.",
    );
    if (ok) setOpen(false);
  }
  return (
    <div className="save-setup">
      {open ? (
        <form onSubmit={save} className="save-setup-form">
          <input
            aria-label="Setup name"
            value={name}
            maxLength={80}
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="secondary">
            <Check size={15} /> Save
          </button>
          <button type="button" className="text-button" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <button
          className="secondary"
          onClick={() => {
            setOpen(true);
            setStatus("");
          }}
        >
          <Bookmark size={15} /> Save setup
        </button>
      )}
      {status && (
        <span className="save-setup-status" role="status">
          {status}
        </span>
      )}
    </div>
  );
}

/** One plan: calendar, blocks, numbers, and (for plans, not the current farm) actions. */
export default function PlanCard({ title, eyebrow, part, farm, onBacktest, compact = false, tone = "" }) {
  return (
    <CalcRecords records={part.calculations}>
    <article className={`opt-plan ${compact ? "opt-compact" : ""} ${tone}`}>
      <header>
        <span className="eyebrow">{eyebrow}</span>
        <h3>{title}</h3>
      </header>
      <MiniCalendar blocks={part.blocks} />
      <BlockList blocks={part.blocks} />
      <Stats stats={part.summary_stats} blocks={part.blocks} compact={compact} />
      {part.budget?.budget_usd != null && (
        <p className="caption">
          {part.budget.years_over_budget?.length
            ? `Cost is over the ${money(part.budget.budget_usd)} budget in ${part.budget.years_over_budget.length} of ${part.summary_stats?.years_count ?? "?"} years.`
            : `Cost stays within the ${money(part.budget.budget_usd)} budget in every year.`}
        </p>
      )}
      {farm && (
        <div className="opt-actions">
          <button className="primary" onClick={() => onBacktest(farm)}>
            <Play size={15} /> Backtest this plan
          </button>
          <SavePlan farm={farm} stats={part.summary_stats} defaultName={title} />
        </div>
      )}
    </article>
    </CalcRecords>
  );
}
