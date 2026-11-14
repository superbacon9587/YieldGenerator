// Pure helpers for Part A: land check, period presets, summary numbers, budget.
// Every helper tolerates an older backend that does not send the new fields.
import { MONTHS, activeMonth, mean } from "../../domain.js";

export const DEFAULT_PERIOD = "20";
export const FALLBACK_META = Object.freeze({
  first_year: 1985,
  last_full_year: new Date().getFullYear() - 1,
  presets: [5, 10, 20, 30, 40],
});

/** Acres in the ground for each month, January first. Nov to Apr wraps. */
export function monthlyAcres(blocks) {
  return MONTHS.map((_, i) =>
    blocks.reduce(
      (sum, b) =>
        activeMonth(i + 1, Number(b.start_month), Number(b.end_month))
          ? sum + (Number(b.acres) || 0)
          : sum,
      0,
    ),
  );
}

/** Peak use, its month, and the months over the available acreage. */
export function landCheck(blocks, available) {
  const perMonth = monthlyAcres(blocks);
  const peak = Math.max(0, ...perMonth);
  const limit = Number(available);
  const hasLimit = Number.isFinite(limit) && limit > 0;
  return {
    perMonth,
    peak,
    peakMonth: MONTHS[perMonth.indexOf(peak)] ?? MONTHS[0],
    overMonths: hasLimit
      ? MONTHS.filter((_, i) => perMonth[i] > limit + 1e-6)
      : [],
    available: hasLimit ? limit : null,
  };
}

/** [first, last] for an N-year preset ending at the last full year. */
export function presetYears(preset, meta = FALLBACK_META) {
  const n = Number(preset);
  const last = meta.last_full_year;
  return [Math.max(meta.first_year, last - n + 1), last];
}

/** Presets that fit the history, falling back when /api/meta is unavailable. */
export function availablePresets(meta) {
  const m = meta ?? FALLBACK_META;
  const span = m.last_full_year - m.first_year + 1;
  return (m.presets ?? FALLBACK_META.presets).filter((p) => p <= span);
}

export function periodLabel(years) {
  if (!Array.isArray(years) || !years.length) return "";
  const first = years[0],
    last = years.at(-1);
  return `${last - first + 1}-year backtest, ${first} to ${last}`;
}

/** Average yearly farm harvest in tons from yield_weight, or null. */
export function avgYieldTons(result) {
  const totals = new Map();
  for (const w of result?.yield_weight ?? [])
    for (const r of w?.yearly ?? [])
      if (typeof r?.tons === "number")
        totals.set(r.year, (totals.get(r.year) ?? 0) + r.tons);
  return mean([...totals.values()]);
}

/**
 * summary_stats from the backend, or the same numbers computed from
 * farm_totals and yield_weight. A partial summary_stats (an older backend or
 * the demo fixture, which only send avg_yield_tons) is filled in.
 */
export function summaryOf(result) {
  const sent = result?.summary_stats;
  if (sent && sent.years_count != null) return sent;
  const rows = result?.farm_totals ?? [];
  const profits = rows.map((r) => r.profit).filter((v) => v != null);
  return {
    years_count: rows.length,
    total_profit: profits.length ? profits.reduce((a, b) => a + b, 0) : null,
    avg_profit: mean(profits),
    avg_relative_yield: mean(rows.map((r) => r.relative_yield)),
    avg_water_applied_af: mean(rows.map((r) => r.water_applied_af)),
    avg_cost: mean(rows.map((r) => r.cost)),
    avg_yield_tons: avgYieldTons(result),
    ...sent,
  };
}

const usd = (v) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(v);

/** "Costs went over your budget in 2 of 20 years (2014, 2022). Largest overrun: $18,000." */
export function budgetMessage(budget, yearsCount) {
  const years = budget?.years_over_budget ?? [];
  if (!years.length) return null;
  const overrun =
    budget.max_overrun_usd == null
      ? ""
      : ` Largest overrun: ${usd(budget.max_overrun_usd)}.`;
  return `Costs went over your budget in ${years.length} of ${yearsCount} years (${years.join(", ")}).${overrun}`;
}

/** Fill Part A fields on a farm saved before they existed. */
export function withPartADefaults(farm) {
  const acres = (farm.blocks ?? []).reduce(
    (s, b) => s + (Number(b.acres) || 0),
    0,
  );
  return {
    ...farm,
    available_acres: farm.available_acres ?? acres,
    period: farm.period ?? "custom",
    optional: { budget_usd: null, ...farm.optional },
  };
}
