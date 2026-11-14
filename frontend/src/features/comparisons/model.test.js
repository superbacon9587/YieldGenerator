import test from "node:test";
import assert from "node:assert/strict";
import {
  alternativeLabel,
  comparisonChange,
  comparisonGroups,
  difference,
} from "./model.js";
import { DEFAULT_FARM, clone, scenarioFarm } from "../../domain.js";
const row = {
  block_id: "b3",
  kind: "planting_window",
  current: { irrigation: "flood", start_month: 5, end_month: 9 },
  alternative: { irrigation: "flood", start_month: 4, end_month: 8 },
};
test("missing comparisons hide the section; rows stay with their crop entry", () => {
  assert.deepEqual(comparisonGroups(DEFAULT_FARM, undefined), []);
  const groups = comparisonGroups(DEFAULT_FARM, [row]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].block.id, "b3");
});
test("dates and irrigation are described neutrally", () => {
  assert.equal(
    alternativeLabel(row),
    "Planting Apr to Aug instead of May to Sep",
  );
  assert.equal(
    alternativeLabel({
      ...row,
      kind: "irrigation",
      alternative: { ...row.alternative, irrigation: "drip" },
    }),
    "Drip instead of flood",
  );
});
test("null, zero, profit, water and percentage points are formatted distinctly", () => {
  assert.deepEqual(difference(null, "money"), {
    text: "No price data",
    tone: "unavailable",
  });
  assert.deepEqual(difference(0, "yield"), { text: "0 pts", tone: "neutral" });
  assert.equal(difference(-23.808, "water").tone, "positive");
  assert.equal(difference(-1389, "money").tone, "negative");
  assert.equal(difference(2.64, "yield").text, "+2.64 pts");
});
test("what-if receives exact months and method without changing saved baseline", () => {
  const baseline = clone(DEFAULT_FARM);
  const change = comparisonChange(DEFAULT_FARM, row);
  const next = scenarioFarm(
    DEFAULT_FARM,
    { type: "custom", blockId: row.block_id, ...change },
    {},
  );
  assert.equal(next.blocks[2].start_month, 4);
  assert.equal(next.blocks[2].end_month, 8);
  assert.deepEqual(next.blocks[0], baseline.blocks[0]);
  assert.deepEqual(DEFAULT_FARM, baseline);
  assert.equal(
    comparisonChange(DEFAULT_FARM, { ...row, block_id: "missing" }),
    null,
  );
});
