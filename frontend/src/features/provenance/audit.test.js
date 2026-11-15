import test from "node:test";
import assert from "node:assert/strict";
import { periodCalculation } from "./audit.js";
test("harvest average includes known crop weights without turning unknown-only years into zero", () => {
  const r = {
    years: [2020, 2021, 2022],
    farm_totals: [],
    yield_weight: [
      {
        yearly: [
          { year: 2020, tons: 10 },
          { year: 2021, tons: 20 },
          { year: 2022, tons: null },
        ],
      },
      {
        yearly: [
          { year: 2020, tons: 5 },
          { year: 2021, tons: null },
          { year: 2022, tons: null },
        ],
      },
    ],
  };
  assert.deepEqual(periodCalculation(r, "harvest"), {
    label: "Sum of annual crop harvest totals",
    sum: 35,
    count: 2,
    average: 17.5,
    unit: "US short tons",
  });
});
test("profit explanations include zero and negative values but exclude null", () => {
  const r = {
    farm_totals: [
      { profit: 0 },
      { profit: -10 },
      { profit: null },
      { profit: 40 },
    ],
  };
  const c = periodCalculation(r, "profit");
  assert.equal(c.sum, 30);
  assert.equal(c.count, 3);
  assert.equal(c.average, 10);
});
