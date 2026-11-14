import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DEFAULT_FARM, clone } from "../../domain.js";
import {
  DEFAULT_SETTINGS,
  OBJECTIVES,
  buildRequest,
  demoOptimize,
  differenceCells,
  findBlockers,
  inputHint,
  monthsLabel,
  planToFarm,
  settingsOf,
  tonsByCrop,
} from "./optimizePlan.js";
import { checkResponse, failureMessage } from "./optimizeApi.js";

const farm = (patch = {}) => ({
  ...clone(DEFAULT_FARM),
  available_acres: 100,
  optional: { ...DEFAULT_FARM.optional, budget_usd: 250000 },
  ...patch,
});

test("settings default and drop unknown values", () => {
  assert.deepEqual(settingsOf({}), { ...DEFAULT_SETTINGS });
  const s = settingsOf({
    optimize: { allowed_crops: ["corn", "kale"], objective: "tons", max_share_per_crop: 0.5 },
  });
  assert.deepEqual(s.allowed_crops, ["corn"]);
  assert.equal(s.objective, "profit");
  assert.equal(s.max_share_per_crop, 0.5);
  assert.equal(s.min_block_acres, 5);
  assert.equal(s.allow_new_perennials, false);
});

test("Find stays disabled until acreage and budget are filled", () => {
  const empty = farm({ available_acres: "", optional: { ...DEFAULT_FARM.optional, budget_usd: null } });
  assert.deepEqual(findBlockers(empty), [
    "Enter the available acreage.",
    "Enter the yearly operating budget.",
  ]);
  assert.deepEqual(findBlockers(farm({ optional: { ...DEFAULT_FARM.optional, budget_usd: "" } })), [
    "Enter the yearly operating budget.",
  ]);
  assert.deepEqual(findBlockers(farm()), []);
  assert.deepEqual(findBlockers(farm({ optional: { ...DEFAULT_FARM.optional, budget_usd: 0 } })), []);
  assert.deepEqual(findBlockers(farm({ optimize: { allowed_crops: [] } })), ["Pick at least one allowed crop."]);
  assert.deepEqual(findBlockers(farm({ available_acres: -2 })), ["Available acreage must be more than 0."]);
});

test("request matches the POST /api/optimize contract", () => {
  const req = buildRequest(farm());
  assert.deepEqual(Object.keys(req).sort(), [
    "allow_new_perennials", "allowed_crops", "allowed_irrigation", "available_acres",
    "budget_rule", "budget_usd", "current_farm", "location", "max_share_per_crop",
    "min_block_acres", "objective", "price_mode", "soil", "water_available_af", "years",
  ]);
  assert.equal(req.allowed_crops, null); // every crop checked means no filter
  assert.equal(req.allowed_irrigation, null);
  assert.equal(req.objective, "profit");
  assert.equal(req.budget_rule, "every_year");
  assert.equal(req.max_share_per_crop, 0.7);
  assert.equal(req.min_block_acres, 5);
  assert.equal(req.water_available_af, null);
  assert.equal(req.current_farm.blocks.length, DEFAULT_FARM.blocks.length);
  const custom = buildRequest(
    farm({
      available_acres: "80",
      optional: { ...DEFAULT_FARM.optional, budget_usd: "120000", water_available_af: "300" },
      optimize: {
        allowed_crops: ["corn", "oats"],
        allowed_irrigation: ["drip"],
        objective: "production_value",
        budget_rule: "average",
        allow_new_perennials: true,
        min_block_acres: "10",
      },
    }),
  );
  assert.equal(custom.available_acres, 80);
  assert.equal(custom.budget_usd, 120000);
  assert.equal(custom.water_available_af, 300);
  assert.deepEqual(custom.allowed_crops, ["corn", "oats"]);
  assert.deepEqual(custom.allowed_irrigation, ["drip"]);
  assert.equal(custom.objective, "production_value");
  assert.equal(custom.budget_rule, "average");
  assert.equal(custom.allow_new_perennials, true);
  assert.equal(custom.min_block_acres, 10);
});

test("a plan becomes a farm with plain blocks and the same settings", () => {
  const base = farm({ optimize: { objective: "profit_per_af" } });
  const next = planToFarm(base, [
    { id: "p1", crop: "corn", acres: 30.5, irrigation: "drip", start_month: 6, end_month: 10,
      avg_profit: 1000, avg_yield_tons: 80 },
  ]);
  assert.deepEqual(next.blocks, [
    { id: "p1", crop: "corn", acres: 30.5, irrigation: "drip", start_month: 6, end_month: 10 },
  ]);
  assert.equal(next.available_acres, 100);
  assert.equal(next.optional.budget_usd, 250000);
  assert.equal(next.optimize.objective, "profit_per_af");
  assert.equal(base.blocks.length, DEFAULT_FARM.blocks.length); // input not changed
});

test("labels, tons per crop, and difference colors", () => {
  assert.equal(monthsLabel(1, 12), "Year-round");
  assert.equal(monthsLabel(11, 3), "Nov to Mar");
  assert.deepEqual(
    tonsByCrop([
      { crop: "corn", avg_yield_tons: 10 },
      { crop: "almonds", avg_yield_tons: 40 },
      { crop: "corn", avg_yield_tons: 5 },
      { crop: "oats", avg_yield_tons: null },
    ]),
    [["almonds", 40], ["corn", 15]],
  );
  const cells = differenceCells({ avg_profit: 500, avg_yield_tons: -3, avg_water_applied_af: -20, avg_cost: 100 });
  assert.deepEqual(cells.map((c) => c.tone), ["positive", "negative", "positive", "negative"]);
  assert.deepEqual(differenceCells({ avg_profit: 0 }).map((c) => c.tone), ["flat", "flat", "flat", "flat"]);
  for (const o of Object.values(OBJECTIVES)) assert.match(o.plan, /^Highest .* plan$/);
});

test("infeasible reasons from the backend name the related input", () => {
  const cases = [
    ["The locked almond acres cost more than the budget in 2022.", "yearly operating budget"],
    ["The locked almond acres (80) are more than the 60 available acres.", "available acreage"],
    ["The locked almond acres (80) are more than the 70% crop share limit (70 acres).", "max share"],
    ["The locked almond acres need more water than the limit in 2021.", "water available per year"],
    ["The current 40 almond acres are locked, but almonds are not in the allowed crops.", "Allow new orchards"],
    ["The 5 acre minimum block is larger than the 4 acres each crop can use.", "minimum block size"],
    ["Even a 5 acre block of the cheapest option (oat, drip, Oct to Feb) costs $1,250 in its costliest year, more than the $100 budget.", "yearly operating budget"],
    ["No crop options are left to plan with. Walnuts was left out: new perennial plantings are off.", "allowed irrigation"],
  ];
  for (const [reason, input] of cases) assert.ok(inputHint("infeasible", reason).includes(input), reason);
  assert.match(inputHint("no_profitable_plan", "No allowed option makes money"), /allowed crops/);
  assert.match(inputHint("infeasible", "something new"), /Related inputs/);
});

test("demo response has the real shape and passes the response check", () => {
  const req = buildRequest(farm());
  const r = checkResponse(demoOptimize(req));
  assert.equal(r.status, "optimal");
  assert.equal(r.plan.blocks.length, DEFAULT_FARM.blocks.length);
  for (const part of [r.plan, r.current_farm, ...r.alternatives]) {
    assert.ok(part.summary_stats.avg_yield_tons > 0);
    for (const b of part.blocks) assert.ok("avg_profit" in b && "avg_yield_tons" in b);
  }
  assert.equal(r.alternatives[0].label, "Alternative 1");
  assert.match(r.assumptions[0], /^DEMO DATA/);
});

test("response check and HTTP failures", () => {
  assert.throws(() => checkResponse({ status: "maybe", assumptions: [] }), /contract/);
  assert.throws(() => checkResponse({ status: "optimal", assumptions: [], plan: { blocks: [] } }), /without blocks/);
  const infeasible = checkResponse({ status: "infeasible", plan: null, assumptions: ["x"], infeasible_reason: "y" });
  assert.deepEqual(infeasible.alternatives, []);
  assert.match(failureMessage(404, { detail: "Not Found" }), /no optimizer yet/);
  assert.match(
    failureMessage(422, { detail: [{ loc: ["body", "budget_usd"], msg: "Field required" }] }),
    /budget_usd: Field required/,
  );
  assert.match(failureMessage(500, null), /\(500\)/);
});

test("no advice language or em dashes in the Optimize tab", () => {
  const banned = /you should|we recommend|\bbest\b|switch to|\u2014/i;
  for (const file of ["OptimizePage.jsx", "PlanCard.jsx", "optimizePlan.js", "optimizeApi.js", "optimize.css"]) {
    const text = readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
    assert.equal(text.match(banned), null, file);
  }
  const strings = [
    ...Object.values(OBJECTIVES).flatMap((o) => [o.title, o.plan, o.blurb, o.note ?? ""]),
    inputHint("no_profitable_plan"),
    failureMessage(404),
    ...demoOptimize(buildRequest(farm())).assumptions,
  ];
  for (const s of strings) assert.equal(s.match(banned), null, s);
});
