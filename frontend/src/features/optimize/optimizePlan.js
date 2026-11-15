// Pure helpers for the Optimize tab (Part C). No React here, so node --test can run them.
// Contract: docs/api_contract.md, "POST /api/optimize".
import { CROPS, IRRIGATION, MONTHS, clone, toSimulateRequest, validateFarm } from "../../domain.js";
import { generateMock } from "../../mock/generate.js";
import { summaryOf, monthlyAcres } from "../summary/landBudget.js";

export const OBJECTIVES = {
  profit: {
    title: "Highest profit",
    plan: "Highest profit plan",
    blurb: "Average yearly revenue minus cost.",
  },
  production_value: {
    title: "Highest yield value",
    plan: "Highest yield value plan",
    blurb: "Average yearly value of the harvest.",
    note:
      "Crops are compared by the dollar value of their harvest at today's prices, because a ton of alfalfa and a ton of almonds are not worth the same.",
  },
  profit_per_af: {
    title: "Highest profit per acre-ft",
    plan: "Highest profit per acre-ft plan",
    blurb: "Average profit for each acre-foot of water applied.",
  },
};

export const BUDGET_RULES = {
  every_year: "Stay within budget every year",
  average: "Stay within budget on average",
};

export const DEFAULT_SETTINGS = Object.freeze({
  budget_rule: "every_year",
  objective: "profit",
  allowed_crops: Object.keys(CROPS),
  allowed_irrigation: Object.keys(IRRIGATION),
  allow_new_perennials: false,
  max_share_per_crop: 0.7,
  min_block_acres: 5,
});

/** Optimize settings saved on the farm (farm.optimize), with defaults filled in. */
export function settingsOf(farm) {
  const saved = farm?.optimize ?? {};
  const pick = (list, known) =>
    Array.isArray(list) ? list.filter((x) => known.includes(x)) : [...known];
  return {
    ...DEFAULT_SETTINGS,
    ...saved,
    allowed_crops: pick(saved.allowed_crops, DEFAULT_SETTINGS.allowed_crops),
    allowed_irrigation: pick(saved.allowed_irrigation, DEFAULT_SETTINGS.allowed_irrigation),
    objective: OBJECTIVES[saved.objective] ? saved.objective : DEFAULT_SETTINGS.objective,
    budget_rule: BUDGET_RULES[saved.budget_rule] ? saved.budget_rule : DEFAULT_SETTINGS.budget_rule,
  };
}

const blank = (v) => v === "" || v == null;
const toNumber = (v) => (blank(v) ? null : Number(v));

/** Problems that keep "Find plan" disabled, in plain words. Empty when ready. */
export function findBlockers(farm) {
  const s = settingsOf(farm);
  const out = [];
  const acres = toNumber(farm.available_acres);
  const budget = toNumber(farm.optional?.budget_usd);
  if (acres == null) out.push("Enter the available acreage.");
  else if (!Number.isFinite(acres) || acres <= 0) out.push("Available acreage must be more than 0.");
  if (budget == null) out.push("Enter the yearly operating budget.");
  else if (!Number.isFinite(budget) || budget < 0) out.push("The yearly budget must be 0 or more.");
  const water = toNumber(farm.optional?.water_available_af);
  if (water != null && (!Number.isFinite(water) || water < 0))
    out.push("Water available must be 0 or more, or left blank.");
  if (!s.allowed_crops.length) out.push("Pick at least one allowed crop.");
  if (!s.allowed_irrigation.length) out.push("Pick at least one irrigation type.");
  const minBlock = Number(s.min_block_acres);
  if (!Number.isFinite(minBlock) || minBlock < 0) out.push("Minimum block size must be 0 or more.");
  return out;
}

/** The POST /api/optimize body for the farm and its saved optimize settings. */
export function buildRequest(farm) {
  const base = toSimulateRequest(farm);
  const s = settingsOf(farm);
  const all = (list, known) => (list.length === known.length ? null : list);
  return {
    location: base.location,
    years: base.years,
    price_mode: base.price_mode,
    available_acres: Number(farm.available_acres),
    budget_usd: Number(farm.optional.budget_usd),
    budget_rule: s.budget_rule,
    water_available_af: base.optional.water_available_af,
    objective: s.objective,
    allowed_crops: all(s.allowed_crops, DEFAULT_SETTINGS.allowed_crops),
    allowed_irrigation: all(s.allowed_irrigation, DEFAULT_SETTINGS.allowed_irrigation),
    allow_new_perennials: Boolean(s.allow_new_perennials),
    max_share_per_crop: Number(s.max_share_per_crop),
    min_block_acres: Number(s.min_block_acres),
    soil: base.optional.soil,
    surface_water_share: Number(base.optional.surface_water_share ?? 0.5),
    current_farm: { blocks: base.blocks },
  };
}

/** Location, years, and block checks shared with the farm form. */
export function farmErrors(farm) {
  return validateFarm(toSimulateRequest(farm));
}

/** A farm form state with the plan's blocks, ready for the backtest or a saved setup. */
export function planToFarm(farm, blocks) {
  const next = clone(farm);
  next.blocks = blocks.map(({ id, crop, acres, irrigation, start_month, end_month }) => ({
    id,
    crop,
    acres,
    irrigation,
    start_month,
    end_month,
  }));
  return next;
}

/** "Mar to Jul", or "Year-round" for 1 to 12. */
export function monthsLabel(start, end) {
  if (Number(start) === 1 && Number(end) === 12) return "Year-round";
  return `${MONTHS[start - 1]} to ${MONTHS[end - 1]}`;
}

/** Average harvest in tons for each crop, largest first: [[crop, tons], ...]. */
export function tonsByCrop(blocks) {
  const totals = new Map();
  for (const b of blocks ?? [])
    if (typeof b.avg_yield_tons === "number")
      totals.set(b.crop, (totals.get(b.crop) ?? 0) + b.avg_yield_tons);
  return [...totals.entries()].sort((a, b) => b[1] - a[1]);
}

/**
 * Difference cells for plan minus current. For profit and harvest, higher is
 * shown green; for water and cost, lower is shown green.
 */
export function differenceCells(diff) {
  const rows = [
    ["avg_profit", "Profit", false],
    ["avg_yield_tons", "Harvest", false],
    ["avg_water_applied_af", "Water", true],
    ["avg_cost", "Cost", true],
  ];
  return rows.map(([key, label, lowerIsGreen]) => {
    const value = diff?.[key] ?? null;
    let tone = "flat";
    if (value != null && value !== 0)
      tone = (value < 0) === lowerIsGreen ? "positive" : "negative";
    return { key, label, value, tone };
  });
}

/**
 * Neutral sentence naming the input behind an infeasible or no-plan result.
 * Matches the backend's infeasible_reason wording (backend/optimize.py).
 */
export function inputHint(status, reason = "") {
  const r = reason.toLowerCase();
  if (status === "no_profitable_plan")
    return "Related inputs: allowed crops, objective, and backtest years. No allowed option earns a profit over these years at this location.";
  if (r.includes("locked") && r.includes("cost more than the budget"))
    return "Related input: yearly operating budget. The budget is lower than the cost of the locked orchard acres.";
  if (r.includes("locked") && r.includes("available acres"))
    return "Related input: available acreage. It is smaller than the locked orchard acres.";
  if (r.includes("locked") && r.includes("share limit"))
    return "Related input: max share for any one crop. The share limit is smaller than the locked orchard acres.";
  if (r.includes("locked") && r.includes("minimum block"))
    return "Related input: minimum block size. It is larger than the locked orchard acres.";
  if (r.includes("locked") && r.includes("water"))
    return "Related input: water available per year. It is lower than the water the locked orchard acres need.";
  if (r.includes("not in the allowed crops"))
    return "Related inputs: allowed crops and Allow new orchards. An orchard crop on the current farm is left out of the allowed crops while its acres stay fixed.";
  if (r.includes("minimum block is larger"))
    return "Related inputs: minimum block size, available acreage, and max share for any one crop. The minimum block is larger than the acres one crop can use.";
  if (r.includes("budget"))
    return "Related input: yearly operating budget. The budget is lower than the cost of the smallest block of any allowed option.";
  if (r.includes("water"))
    return "Related input: water available per year. It is lower than the water the smallest block of any allowed option needs.";
  if (r.includes("no crop options are left"))
    return "Related inputs: allowed crops and allowed irrigation. No remaining option has price and cost data for this location.";
  return "Related inputs: available acreage, budget, water, and the crop limits. Together they leave no plan.";
}

// ---------------------------------------------------------------- demo mode

const DEMO_NOTE =
  "DEMO DATA: this sample plan is built from synthetic numbers for interface testing. It is not an optimization and uses no NASA observations.";

function demoPart(farm, blocks) {
  const result = generateMock({ ...farm, blocks });
  const weights = new Map((result.yield_weight ?? []).map((w) => [w.block_id, w]));
  const out = result.blocks.map((b) => {
    const profits = b.yearly.map((y) => y.profit).filter((v) => v != null);
    return {
      id: b.id,
      crop: b.crop,
      acres: b.acres,
      irrigation: b.irrigation,
      start_month: b.start_month,
      end_month: b.end_month,
      avg_profit: profits.length ? Math.round(profits.reduce((a, c) => a + c, 0) / profits.length) : null,
      avg_yield_tons: weights.get(b.id)?.avg_tons ?? null,
    };
  });
  const stats = summaryOf(result);
  const budget = farm.optional?.budget_usd == null ? null : Number(farm.optional.budget_usd);
  const over = budget == null ? [] : result.farm_totals.filter((t) => t.cost > budget);
  return {
    blocks: out,
    summary_stats: stats,
    budget: {
      budget_usd: budget,
      years_over_budget: over.map((t) => t.year),
      max_overrun_usd: over.length ? Math.max(...over.map((t) => t.cost - budget)) : null,
    },
  };
}

/** A sample response with the real shape, for Demo mode only. */
export function demoOptimize(request) {
  const farm = {
    location: request.location,
    years: request.years,
    optional: { water_available_af: request.water_available_af, budget_usd: request.budget_usd },
  };
  const current = request.current_farm.blocks.map((b) => ({ ...b }));
  const allowed = new Set(request.allowed_irrigation ?? Object.keys(IRRIGATION));
  const irrigation = allowed.has("drip") ? "drip" : [...allowed][0];
  const plan = current.map((b, i) => ({ ...b, id: `p${i + 1}`, irrigation }));
  const alt = plan.map((b) => ({ ...b, acres: Math.round(b.acres * 0.9 * 10) / 10 }));
  const planPart = demoPart(farm, plan);
  const currentPart = demoPart(farm, current);
  const altPart = demoPart(farm, alt);
  const land = monthlyAcres(plan);
  const peak = Math.max(...land);
  const diff = (k, d) => {
    const a = planPart.summary_stats[k],
      b = currentPart.summary_stats[k];
    return a == null || b == null ? null : Number((a - b).toFixed(d));
  };
  return {
    status: "optimal",
    objective: request.objective,
    plan: {
      ...planPart,
      land: {
        available_acres: request.available_acres,
        peak_acres_in_use: peak,
        peak_month: MONTHS[land.indexOf(peak)],
        over_capacity_months: MONTHS.filter((_, i) => land[i] > request.available_acres),
      },
    },
    current_farm: currentPart,
    difference_vs_current: {
      avg_profit: diff("avg_profit", 0),
      avg_yield_tons: diff("avg_yield_tons", 2),
      avg_water_applied_af: diff("avg_water_applied_af", 1),
      avg_cost: diff("avg_cost", 0),
    },
    alternatives: [{ label: "Alternative 1", ...altPart }],
    binding_constraints: ["Sample only: limits are not computed in Demo mode."],
    infeasible_reason: null,
    error_detail: null,
    options_considered: plan.length,
    assumptions: [DEMO_NOTE],
  };
}
