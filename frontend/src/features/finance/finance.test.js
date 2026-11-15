import test from "node:test";
import assert from "node:assert/strict";
import {
  financialRows,
  financialYear,
  expenseTotals,
  roundingDifference,
  cropSeries,
} from "./finance.js";
const result = {
  years: [2021, 2022],
  farm_totals: [
    { year: 2021, revenue: 200, cost: 150, profit: 50 },
    { year: 2022, revenue: 220, cost: 151, profit: 69 },
  ],
  blocks: [
    {
      id: "a",
      crop: "almonds",
      yearly: [
        { year: 2021, revenue: 190, cost: 130, profit: 60 },
        { year: 2022, revenue: 200, cost: 131, profit: 69 },
      ],
    },
    {
      id: "c",
      crop: "corn",
      yearly: [
        { year: 2021, revenue: 10, cost: 20, profit: -10 },
        { year: 2022, revenue: 20, cost: 20, profit: 0 },
      ],
    },
    {
      id: "o",
      crop: "oats",
      yearly: [
        { year: 2021, revenue: null, cost: null, profit: null },
        { year: 2022, revenue: null, cost: null, profit: null },
      ],
    },
  ],
  calculation_details: {
    blocks: [
      {
        id: "a",
        yearly: [
          {
            year: 2021,
            production_cost_excl_water: 100,
            surface_water_cost: 10,
            groundwater_cost: 20,
          },
        ],
      },
      {
        id: "c",
        yearly: [
          {
            year: 2021,
            production_cost_excl_water: 10,
            surface_water_cost: 4,
            groundwater_cost: 6,
          },
        ],
      },
    ],
  },
};
test("profit contributions preserve losses and unavailable crops; net is separately reported", () => {
  const rows = financialRows(result, "profit");
  assert.equal(rows[0].a, 60);
  assert.equal(rows[0].c, -10);
  assert.equal(rows[0].o, null);
  assert.equal(rows[0].net, 50);
  assert.deepEqual(
    cropSeries(result, "profit").map((s) => s.key),
    ["a", "c"],
  );
});
test("expense categories reconcile only priced crop costs and are unavailable without trace", () => {
  const year = financialYear(result, 2021);
  assert.deepEqual(expenseTotals(year.entries), {
    production: 110,
    surface: 14,
    groundwater: 26,
  });
  const series = financialRows(result, "cost", "expense");
  assert.equal(
    series[0].production + series[0].surface + series[0].groundwater,
    series[0].net,
  );
  assert.equal(expenseTotals(financialYear(result, 2022).entries), null);
});
test("year selection picks exact crop row and rounding remains explicit", () => {
  const y = financialYear(result, 2022);
  assert.equal(y.entries[0].row.revenue, 200);
  assert.equal(roundingDifference(y.entries, 151, "cost"), 0);
  assert.equal(roundingDifference(y.entries, 152, "cost"), 1);
  assert.equal(roundingDifference(y.entries, null, "profit"), null);
});
