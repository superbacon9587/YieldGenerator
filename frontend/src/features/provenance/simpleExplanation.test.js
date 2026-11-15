import test from "node:test";
import assert from "node:assert/strict";
import { simpleExplanation } from "./simpleExplanation.js";
const trace = {
  year: 2021,
  baseline_tons_per_acre: 0.98,
  baseline_yield: {
    value: 1960,
    unit: "LB / ACRE",
    source: "USDA statewide median, 1995-2026",
  },
  median_relative_yield: 0.9835,
  displayed: { relative_yield: 0.931 },
  harvest_tons_per_acre: 0.9276868327,
  harvest_tons: 37.1074733,
  season_start: "2021-01-01",
  season_end: "2021-12-31",
  weather_source: {
    url: "https://power.larc.nasa.gov/test",
    label: "NASA 2021",
  },
  crop_price: { value: 2.6, unit: "$ / LB", year: 2025 },
  sale_quantity: 74214.9466,
  revenue_unrounded: 192958.8612,
  cost_unrounded: 133461.4951,
  profit_unrounded: 59497.3661,
  production_cost_per_acre: 3083,
  production_cost_source: { source: "UC cost study 2024" },
  price_source: { url: "https://example.com/prices", label: "Price" },
};
const result = {
  years: [2020, 2021],
  summary: { best_year: 2020, worst_year: 2021 },
  assumptions: [],
  farm_totals: [
    { year: 2020, profit: 10, water_applied_af: 20, relative_yield: 1 },
    { year: 2021, profit: 20, water_applied_af: 40, relative_yield: 0.9 },
  ],
  blocks: [{ id: "a", crop: "almonds" }],
  calculation_details: {
    blocks: [
      { id: "a", crop: "almonds", acres: 40, sources: [], yearly: [trace] },
    ],
    excluded_financial_blocks: [],
    reconciliation: { avg_revenue: 30, avg_cost: 15, avg_profit: 15 },
    model_source: { url: "https://example.com/model", label: "Model" },
  },
};
test("full yield is derived from CSV baseline and fixed model reference, not taken from NASA", () => {
  const e = simpleExplanation(
    result,
    { metric: "full_yield", blockId: "a" },
    "lb",
  );
  assert.match(e.formula, /1,960 lb\/acre/);
  assert.match(e.formula, /1,992\.8826/);
  assert.match(e.note, /CSV provides a typical median yield, not full yield/);
});
test("selected crop/year gets one relevant calculation and distinguishes price year", () => {
  const e = simpleExplanation(result, {
    metric: "revenue",
    blockId: "a",
    year: 2021,
  });
  assert.match(e.scope, /2021/);
  assert.match(e.formula, /74,214\.9466/);
  assert.match(e.origins[0].text, /2025/);
  assert.equal(
    e.links.some((x) => x.url.includes("prices")),
    true,
  );
});
test("summary is short and does not enumerate individual years", () => {
  const e = simpleExplanation(result, { metric: "total_profit" });
  assert.match(e.formula, /2 included yearly/);
  assert.match(e.formula, /\$30/);
  assert.ok(e.formula.length < 160);
});
test("missing trace reports unavailable and does not invent zero harvest", () => {
  const e = simpleExplanation(
    { ...result, calculation_details: null },
    { metric: "harvest" },
  );
  assert.match(e.formula, /unavailable/);
  const r = structuredClone(result);
  r.calculation_details.blocks[0].yearly[0].harvest_tons = null;
  assert.match(
    simpleExplanation(r, { metric: "harvest", blockId: "a", year: 2021 })
      .formula,
    /unavailable/,
  );
});

test("partial margin uses matching sales and costs, not all known sales", () => {
  const r = structuredClone(result);
  r.financial_coverage = {margin:{complete:false,included_block_ids:["a"],total_blocks:2}};
  Object.assign(r.calculation_details.reconciliation, {avg_revenue:1000, matched_avg_revenue:30, matched_avg_cost:15});
  const e = simpleExplanation(r, {metric:"avg_profit"});
  assert.match(e.formula, /\$30/);
  assert.doesNotMatch(e.formula, /1,000/);
  assert.match(e.note, /Whole-farm margin is unavailable/);
});
