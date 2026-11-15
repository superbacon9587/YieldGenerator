// Table rows for small hand-made responses (moved to the shared selector, chartData.js).
import test from "node:test";
import assert from "node:assert/strict";
import { getChartRows, tableRecordId } from "../provenance/chartData.js";

const result = {
  years: [2014, 2015],
  summary: { drought_years: [2014] },
  blocks: [
    {
      id: "a",
      crop: "almonds",
      acres: 40,
      yearly: [
        { year: 2014, water_applied_af: 120, relative_yield: 0.9, revenue: 100000, cost: 80000, profit: 20000 },
        { year: 2015, water_applied_af: 100, relative_yield: 0.8, revenue: 90000, cost: 85000, profit: 5000 },
      ],
    },
    {
      id: "o",
      crop: "oats",
      acres: 10,
      yearly: [
        { year: 2014, water_applied_af: 10, relative_yield: 1, revenue: null, cost: null, profit: null },
        { year: 2015, water_applied_af: 12, relative_yield: 1, revenue: null, cost: null, profit: null },
      ],
    },
  ],
  farm_totals: [
    { year: 2014, water_applied_af: 130, relative_yield: 0.92, revenue: 100000, cost: 80000, profit: 20000 },
    { year: 2015, water_applied_af: 112, relative_yield: 0.84, revenue: 90000, cost: 85000, profit: 5000 },
  ],
  yield_weight: [
    { block_id: "a", yearly: [{ year: 2014, tons: 40, tons_per_acre: 1 }, { year: 2015, tons: 36, tons_per_acre: 0.9 }] },
    { block_id: "o", yearly: [{ year: 2014, tons: null, tons_per_acre: null }, { year: 2015, tons: null, tons_per_acre: null }] },
  ],
};
const rows = (scope, perAcre = false, unit = "tons") =>
  getChartRows(result, { chart: "yield", scope, perAcre, unit });

test("farm totals add known harvest and keep missing money as null, not zero", () => {
  const { rows: r, average } = rows("farm");
  assert.deepEqual(r.map((x) => x.harvest), [40, 36]);
  assert.deepEqual(r.map((x) => x.margin), [20000, 5000]);
  assert.equal(r[0].marginPct, 20);
  assert.equal(r[0].yield, 92);
  assert.equal(r[0].drought, true);
  assert.equal(average.harvest, 38);
  assert.equal(average.sales, 95000);
  assert.equal(average.margin, 12500);
  assert.equal(average.marginPct, 13.2);
});

test("farm per acre divides by the acres each column covers", () => {
  const r = rows("farm", true).rows;
  assert.equal(r[0].harvest, 1); // only almonds have harvest weight
  assert.equal(r[0].sales, 2500); // only almonds have money
  assert.equal(r[0].water, 2.6); // 130 acre-ft over both entries, to 0.01
});

test("one crop shows that crop's rows; per acre uses tons per acre; pounds convert exactly", () => {
  assert.deepEqual(rows("o").rows.map((x) => x.sales), [null, null]);
  assert.equal(rows("o").average.sales, null);
  assert.deepEqual(rows("a", true).rows.map((x) => x.harvest), [1, 0.9]);
  assert.deepEqual(rows("a", true, "lb").rows.map((x) => x.harvest), [2000, 1800]);
  assert.equal(rows("a", true).rows[1].water, 2.5);
  assert.equal(tableRecordId("a", true, "marginPct"), "table.a.per_acre.margin_pct");
});

test("the whole-farm yield chart stacks crops so the bar top is the table value", () => {
  const data = rows("farm");
  assert.deepEqual(data.series.map((s) => s.key), ["harvest_a"]);
  assert.equal(data.rows[0].harvest_a, 40);
});
