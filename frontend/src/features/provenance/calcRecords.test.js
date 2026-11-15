import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  COST_PART_NAMES,
  costParts,
  differenceRecord,
  formatRecordValue,
  inWeightUnit,
  isEstimated,
  sourceParts,
} from "./calcRecords.js";

const harvest = {
  id: "summary.avg_yield_tons",
  label: "Estimated harvest per year",
  value: 3876.82,
  unit: "tons",
  decimals: 2,
  formula_text: "Sum over crops of (average harvest per acre x acres)",
  is_estimate: true,
  steps: [{ text: "Total = 3,876.82 tons", expr: "3876.82", result: 3876.82 }],
  inputs: [],
};

test("tons records become pounds with one extra step ending in the shown number", () => {
  const lb = inWeightUnit(harvest, "lb");
  assert.equal(lb.unit, "lb");
  assert.equal(lb.value, 7753640);
  assert.equal(lb.steps.length, 2);
  assert.equal(lb.steps.at(-1).text, "3,876.82 tons x 2,000 lb/ton = 7,753,640 lb");
  assert.equal(formatRecordValue(lb), "7,753,640 lb");
  assert.equal(inWeightUnit(harvest, "tons"), harvest);
  const money = { ...harvest, unit: "$", value: 12 };
  assert.equal(inWeightUnit(money, "lb"), money);
});

test("values print with the app's rounding", () => {
  assert.equal(formatRecordValue({ value: -1234.6, unit: "$" }), "-$1,235");
  assert.equal(formatRecordValue({ value: 92.8, unit: "%" }), "92.8%");
  assert.equal(formatRecordValue({ value: 2019, unit: "year" }), "2019");
  assert.equal(formatRecordValue({ value: 12.34, unit: "acre-ft" }), "12.3 acre-ft");
  assert.equal(formatRecordValue({ value: null, unit: "$" }), "Not available");
});

test("a difference record subtracts the two rounded record values", () => {
  const a = { ...harvest, id: "summary.avg_water_applied_af", unit: "acre-ft", decimals: 1, value: 110.4 };
  const b = { ...a, value: 98.1, is_estimate: false, inputs: [] };
  const d = differenceRecord(b, a, "Difference, water");
  assert.equal(d.value, -12.3);
  assert.equal(d.steps[0].text, "98.1 acre-ft - 110.4 acre-ft = -12.3 acre-ft");
  assert.equal(isEstimated(d), true);
  assert.equal(d.inputs.length, 2);
  assert.ok(d.inputs.every((i) => i.source));
  assert.equal(differenceRecord(null, a, "x"), null);
});

const sample = JSON.parse(readFileSync(new URL("./sample_response.json", import.meta.url)));
const CODE_WORDS = /\.py\b|backend\/|function|YieldGenerator model/i;

function checkSources(where, record) {
  for (const i of record.inputs) {
    const at = `${where} / ${i.name}`;
    assert.ok(String(i.source).trim(), at);
    assert.equal(CODE_WORDS.test(i.source), false, `${at}: ${i.source}`);
    for (const link of i.links ?? []) {
      assert.ok(link.url.startsWith("https://"), `${at}: ${link.url}`);
      assert.equal(link.url.includes("github.com"), false, `${at}: ${link.url}`);
    }
    if (i.is_estimate) {
      assert.ok(i.derived_from?.length, `${at}: derived_from`);
      assert.ok(sourceParts(i).links.length, `${at}: publisher link`);
      assert.ok(sourceParts(i).from.startsWith("From: "), at);
    }
  }
}

test("every input in every record has a farmer-readable source with publisher links", () => {
  const records = Object.values(sample.calculations);
  assert.ok(records.length > 50);
  for (const r of records) {
    checkSources(r.id, r);
    if (r.lb) checkSources(`${r.id} (lb)`, r.lb);
    checkSources(`${r.id} (shown in lb)`, inWeightUnit(r, "lb"));
  }
  const c = sample.calculations;
  const diff = differenceRecord(c["summary.avg_cost"], c["summary.avg_cost"], "Difference, cost");
  checkSources(diff.id, diff);
  assert.ok(diff.inputs[0].source.includes('"Estimated cost per year" box'));
});

test("source cell parts: From line, unverified flag, no code links", () => {
  const parts = sourceParts({
    source: "Default assumption: 60% pump efficiency",
    links: [
      { label: "Pump tests", url: "https://jcast.fresnostate.edu/pumpefficiency/pumptesting" },
      { label: "Code", url: "https://github.com/x/y/blob/main/backend/economics.py" },
    ],
    derived_from: ["Default assumption"],
    source_verified: false,
    is_estimate: true,
  });
  assert.equal(parts.from, "From: Default assumption");
  assert.equal(parts.verified, false);
  assert.deepEqual(parts.links.map((l) => l.label), ["Pump tests"]);
  assert.equal(sourceParts({ source: "Farmer input" }).verified, true);
});

test("no record text uses em dashes", () => {
  const text = JSON.stringify([inWeightUnit(harvest, "lb"), differenceRecord(harvest, harvest, "x")]);
  assert.equal(/[–—]/.test(text), false);
});


const SAMPLE = JSON.parse(
  readFileSync(new URL("./sample_response.json", import.meta.url), "utf8"),
);

test("cost info boxes list inputs, harvest, water and irrigation system that add up to the cost", () => {
  const records = Object.values(SAMPLE.calculations);
  const blockCosts = records.filter((r) => /^block\..+\.\d{4}\.cost$/.test(r.id));
  assert.ok(blockCosts.length > 0);
  for (const r of blockCosts) {
    const parts = costParts(r);
    assert.deepEqual(parts.rows.map((p) => p.name), COST_PART_NAMES, r.id);
    assert.equal(Math.round(parts.sum), r.value, r.id);
    assert.equal(parts.sumText, formatRecordValue(r), r.id);
    for (const label of ["Inputs cost:", "Harvest cost:", "Water cost (", "Irrigation system cost"])
      assert.ok(r.steps.some((s) => s.text.startsWith(label)), `${r.id} ${label}`);
  }
  // Table averages and the margin box carry the same four parts.
  const farmCost = SAMPLE.calculations["table.farm.total.cost"];
  assert.deepEqual(costParts(farmCost).rows.map((p) => p.name), COST_PART_NAMES);
  assert.ok(Math.abs(costParts(farmCost).sum - farmCost.value) <= 2);
  const margin = SAMPLE.calculations[blockCosts[0].id.replace(/\.cost$/, ".profit")];
  assert.deepEqual(margin.parts, blockCosts[0].parts);
  assert.equal(costParts({ parts: [] }), null);
  assert.equal(costParts(harvest), null);
});

test("no source link in the sample points to code or a commit", () => {
  const urls = [];
  const walk = (x) => {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object")
      for (const [k, v] of Object.entries(x)) {
        if ((k === "source_url" || k === "url") && typeof v === "string") urls.push(v);
        walk(v);
      }
  };
  walk(SAMPLE.calculations);
  assert.ok(urls.length > 0);
  for (const u of urls) {
    assert.ok(u.startsWith("https://"), u);
    assert.doesNotMatch(u, /github\.com|\.(py|js|jsx)(\?|#|$)|\b[0-9a-f]{40}\b/, u);
  }
});
