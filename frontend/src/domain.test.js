import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_FARM,
  clone,
  activeMonth,
  toAcres,
  requestFromForm,
  validateFarm,
  validateResponse,
  summaryMetrics,
  scenarioFarm,
  money,
} from "./domain.js";
import { generateMock } from "./mock/generate.js";

test("cross-year crop calendar includes Nov-Apr, not summer", () => {
  assert.deepEqual(
    Array.from({ length: 12 }, (_, i) => i + 1).filter((m) =>
      activeMonth(m, 11, 4),
    ),
    [1, 2, 3, 4, 11, 12],
  );
});
test("square feet convert to acres without changing land area", () => {
  assert.equal(toAcres(43560, "sqft"), 1);
  assert.equal(toAcres(40, "acres"), 40);
});
test("request matches contract, preserves zero water and strips UI fields", () => {
  const farm = clone(DEFAULT_FARM);
  farm.blocks[0].displayUnit = "sqft";
  farm.optional.water_available_af = "0";
  farm.optional.water_applied_af = "";
  const r = requestFromForm(farm);
  assert.equal(r.optional.water_available_af, 0);
  assert.equal(r.optional.water_applied_af, null);
  assert.equal("displayUnit" in r.blocks[0], false);
  assert.deepEqual(Object.keys(r), [
    "location",
    "years",
    "price_mode",
    "blocks",
    "optional",
    "available_acres",
  ]);
  assert.equal("period" in r, false);
});
test("blank coordinates are not silently treated as zero", () => {
  const farm = clone(DEFAULT_FARM);
  farm.location.lat = "";
  assert.ok(validateFarm(requestFromForm(farm)).length);
});
test("invalid acreage, invalid water and cross-year coverage fail validation", () => {
  const farm = clone(DEFAULT_FARM);
  farm.blocks[0].acres = -2;
  farm.optional.water_available_af = -1;
  farm.years = [1984, 2024];
  assert.equal(validateFarm(farm).length, 3);
});
test("default farm is valid", () =>
  assert.deepEqual(validateFarm(DEFAULT_FARM), []));
test("null profit is unavailable rather than zero", () => {
  const result = generateMock();
  result.farm_totals.forEach((r) => (r.profit = null));
  assert.equal(summaryMetrics(result).profit, null);
  assert.equal(summaryMetrics(result).worstProfit, null);
  assert.equal(money(null), "No price data");
});
test("water-cut scenario uses baseline mean, preserves baseline and changes mock output", () => {
  const farm = clone(DEFAULT_FARM),
    before = clone(farm),
    base = generateMock(farm);
  const changed = scenarioFarm(farm, { type: "water" }, base);
  assert.equal(
    changed.optional.water_available_af,
    summaryMetrics(base).water * 0.75,
  );
  assert.deepEqual(farm, before);
  assert.ok(
    summaryMetrics(generateMock(changed)).water < summaryMetrics(base).water,
  );
  assert.ok(
    summaryMetrics(generateMock(changed)).yield < summaryMetrics(base).yield,
  );
});
test("drip scenario changes methods but not crop area or baseline", () => {
  const farm = clone(DEFAULT_FARM);
  const next = scenarioFarm(farm, { type: "drip" }, generateMock(farm));
  assert.ok(next.blocks.every((b) => b.irrigation === "drip"));
  assert.equal(farm.blocks[2].irrigation, "flood");
  assert.equal(next.blocks[2].acres, farm.blocks[2].acres);
});
test("mock response follows contract with dynamic years and blocks", () => {
  const farm = clone(DEFAULT_FARM);
  farm.years = [2020, 2024];
  farm.blocks = [{ ...farm.blocks[1], id: "custom" }];
  const r = validateResponse(generateMock(farm));
  assert.equal(r.years.length, 5);
  assert.equal(r.blocks[0].id, "custom");
  assert.equal(r.blocks[0].yearly.length, 5);
  assert.ok(r.assumptions[0].includes("DEMO DATA"));
});
test("missing optional flags do not crash and invalid payloads fail clearly", () => {
  const r = generateMock();
  delete r.waste_flags;
  delete r.assumptions;
  assert.deepEqual(validateResponse(r).waste_flags, []);
  assert.throws(() => validateResponse({}), /API contract/);
});
test("perennial crop swaps update season without mutating baseline", () => {
  const farm = clone(DEFAULT_FARM);
  const next = scenarioFarm(
    farm,
    {
      type: "custom",
      blockId: "b2",
      crop: "almonds",
      acres: 15,
      irrigation: "drip",
    },
    generateMock(farm),
  );
  assert.equal(next.blocks[1].start_month, 1);
  assert.equal(next.blocks[1].end_month, 12);
  assert.equal(farm.blocks[1].start_month, 11);
});
