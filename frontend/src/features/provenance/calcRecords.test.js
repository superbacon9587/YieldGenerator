import test from "node:test";
import assert from "node:assert/strict";
import {
  differenceRecord,
  formatRecordValue,
  inWeightUnit,
  isEstimated,
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

test("no record text uses em dashes", () => {
  const text = JSON.stringify([inWeightUnit(harvest, "lb"), differenceRecord(harvest, harvest, "x")]);
  assert.equal(/[–—]/.test(text), false);
});
