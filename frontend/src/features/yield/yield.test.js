import test from "node:test";
import assert from "node:assert/strict";
import {
  formatAxisTick,
  formatWeight,
  potentialPercent,
  scaleToTons,
  weightWithPotential,
} from "./yieldUnits.js";
import { chartRows, labelsFit, weightByBlock } from "./yieldData.js";
import { generateMock } from "../../mock/generate.js";

test("weights format in tons and pounds", () => {
  assert.equal(formatWeight(1.157, "tons", true), "1.16 tons/acre");
  assert.equal(formatWeight(1.157, "lb", true), "2,314 lb/acre");
  assert.equal(formatWeight(17.4, "lb", false), "34,800 lb");
  assert.equal(formatWeight(null, "tons", true), "No yield data");
  assert.equal(
    weightWithPotential(1.16, 0.934, "tons", true),
    "1.16 tons/acre, 93% of potential",
  );
  assert.equal(potentialPercent(undefined), null);
  assert.equal(formatAxisTick(3600, "lb"), "7.2M");
  assert.equal(formatAxisTick(22.5, "lb"), "45k");
  assert.equal(formatAxisTick(1.5, "tons"), "1.5");
});

test("median year gets the baseline, like the backend", () => {
  assert.deepEqual(
    scaleToTons(4.48, [0.45, 0.9, 1.0]).map((v) => +v.toFixed(3)),
    [2.24, 4.48, 4.978],
  );
  assert.deepEqual(scaleToTons(null, [0.9]), [null]);
  assert.deepEqual(scaleToTons(1, [0, 0]), [null, null]);
});

test("missing yield_weight gives empty rows, not a crash", () => {
  const result = { years: [2001, 2002], blocks: [{ id: "b1" }] };
  assert.equal(weightByBlock(result).size, 0);
  assert.deepEqual(chartRows(result, ["b1"], true), [
    { year: 2001, b1: null, b1__ry: null },
    { year: 2002, b1: null, b1__ry: null },
  ]);
  assert.ok(labelsFit(10, 2));
  assert.ok(!labelsFit(25, 1));
});

test("demo data includes yield_weight and summary_stats", () => {
  const mock = generateMock();
  assert.equal(mock.yield_weight.length, mock.blocks.length);
  assert.ok(mock.summary_stats.avg_yield_tons > 0);
  const row = mock.yield_weight[0].yearly[0];
  assert.ok(
    Math.abs(row.tons - row.tons_per_acre * mock.blocks[0].acres) < 0.02,
  );
});
