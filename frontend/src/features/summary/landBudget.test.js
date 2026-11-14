import test from "node:test";
import assert from "node:assert/strict";
import {
  FALLBACK_META,
  availablePresets,
  budgetMessage,
  landCheck,
  monthlyAcres,
  periodLabel,
  presetYears,
  summaryOf,
  withPartADefaults,
} from "./landBudget.js";
import { DEFAULT_FARM, clone, requestFromForm, validateFarm } from "../../domain.js";

const oats = { id: "b2", crop: "oats", acres: 15, start_month: 11, end_month: 4 };
const corn = { id: "b3", crop: "corn", acres: 15, start_month: 5, end_month: 9 };

test("winter and summer crops share the same acres without overlap", () => {
  assert.deepEqual(monthlyAcres([oats, corn]), [15, 15, 15, 15, 15, 15, 15, 15, 15, 0, 15, 15]);
  const check = landCheck([oats, corn], 15);
  assert.equal(check.peak, 15);
  assert.deepEqual(check.overMonths, []);
});

test("overlapping months are over capacity and named", () => {
  const check = landCheck([oats, { ...corn, start_month: 4, end_month: 8 }], 15);
  assert.equal(check.peak, 30);
  assert.equal(check.peakMonth, "Apr");
  assert.deepEqual(check.overMonths, ["Apr"]);
});

test("land check without acreage reports peak only", () => {
  const check = landCheck(DEFAULT_FARM.blocks, "");
  assert.equal(check.available, null);
  assert.deepEqual(check.overMonths, []);
  assert.equal(check.peak, 55);
});

test("presets end at the last full year and drop periods longer than the record", () => {
  const meta = { first_year: 1985, last_full_year: 2025, presets: [5, 10, 20, 30, 40] };
  assert.deepEqual(presetYears(20, meta), [2006, 2025]);
  assert.deepEqual(presetYears(40, meta), [1986, 2025]);
  assert.deepEqual(availablePresets({ ...meta, last_full_year: 2010 }), [5, 10, 20]);
  assert.deepEqual(availablePresets(undefined), FALLBACK_META.presets);
});

test("period line reads like the plan", () => {
  const years = Array.from({ length: 20 }, (_, i) => 2005 + i);
  assert.equal(periodLabel(years), "20-year backtest, 2005 to 2024");
});

test("budget message only when years went over", () => {
  assert.equal(budgetMessage({ years_over_budget: [] }, 20), null);
  assert.equal(budgetMessage(undefined, 20), null);
  assert.equal(
    budgetMessage({ budget_usd: 250000, years_over_budget: [2014, 2022], max_overrun_usd: 18000 }, 20),
    "Costs went over your budget in 2 of 20 years (2014, 2022). Largest overrun: $18,000.",
  );
});

test("summary uses backend stats, or computes them for an older backend", () => {
  const stats = { years_count: 2, total_profit: 5, avg_profit: 2.5 };
  assert.equal(summaryOf({ summary_stats: stats }), stats);
  const s = summaryOf({
    farm_totals: [
      { relative_yield: 0.9, water_applied_af: 100, profit: 10, cost: 50 },
      { relative_yield: 1.0, water_applied_af: 120, profit: null, cost: null },
    ],
  });
  assert.equal(s.years_count, 2);
  assert.equal(s.total_profit, 10);
  assert.equal(s.avg_profit, 10);
  assert.equal(s.avg_relative_yield, 0.95);
  assert.equal(s.avg_water_applied_af, 110);
  assert.equal(s.avg_cost, 50);
  assert.equal(summaryOf({ farm_totals: [{ relative_yield: 1, water_applied_af: 1, profit: null }] }).total_profit, null);
});

test("request sends available_acres and budget_usd, and validates them", () => {
  const farm = clone(DEFAULT_FARM);
  farm.optional.budget_usd = "250000";
  const r = requestFromForm(farm);
  assert.equal(r.available_acres, 70);
  assert.equal(r.optional.budget_usd, 250000);
  farm.optional.budget_usd = "";
  assert.equal(requestFromForm(farm).optional.budget_usd, null);
  farm.available_acres = "";
  assert.match(validateFarm(requestFromForm(farm)).join(" "), /available acreage/);
  farm.available_acres = 70;
  farm.optional.budget_usd = -1;
  assert.match(validateFarm(requestFromForm(farm)).join(" "), /budget/);
});

test("farms saved before Part A get defaults", () => {
  const old = clone(DEFAULT_FARM);
  delete old.available_acres;
  delete old.period;
  delete old.optional.budget_usd;
  const f = withPartADefaults(old);
  assert.equal(f.available_acres, 70);
  assert.equal(f.period, "custom");
  assert.equal(f.optional.budget_usd, null);
});
