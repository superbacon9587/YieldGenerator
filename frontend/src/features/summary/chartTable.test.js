import test from "node:test";
import assert from "node:assert/strict";
import { averageRow, tableRecordId, tableRows } from "./chartTable.js";

const result = {
  years: [2014, 2015],
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

test("farm totals add known harvest and keep missing money as null, not zero", () => {
  const rows = tableRows(result, "farm", false);
  assert.deepEqual(rows.map((r) => r.harvest), [40, 36]);
  assert.deepEqual(rows.map((r) => r.margin), [20000, 5000]);
  assert.equal(rows[0].marginPct, 20);
  assert.equal(rows[0].yield, 92);
  const avg = averageRow(rows);
  assert.equal(avg.harvest, 38);
  assert.equal(avg.sales, 95000);
  assert.equal(avg.margin, 12500);
  assert.ok(Math.abs(avg.marginPct - (100 * 12500) / 95000) < 1e-9);
});

test("farm per acre divides by the acres each column covers", () => {
  const rows = tableRows(result, "farm", true);
  assert.equal(rows[0].harvest, 1); // only almonds have harvest weight
  assert.equal(rows[0].sales, 2500); // only almonds have money
  assert.equal(rows[0].water, 130 / 50); // water covers both entries
});

test("one crop shows that crop's rows; per acre uses tons per acre", () => {
  const rows = tableRows(result, "o", false);
  assert.deepEqual(rows.map((r) => r.sales), [null, null]);
  assert.equal(averageRow(rows).sales, null);
  assert.deepEqual(tableRows(result, "a", true).map((r) => r.harvest), [1, 0.9]);
  assert.equal(tableRows(result, "a", true)[1].water, 2.5);
  assert.equal(tableRecordId("a", true, "margin_pct"), "table.a.per_acre.margin_pct");
});
