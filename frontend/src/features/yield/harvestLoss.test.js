import test from "node:test";
import assert from "node:assert/strict";
import {
  averageLostPerAcre,
  detailFor,
  harvestSentence,
  lossCause,
  lostTons,
  harvestLossRecord,
} from "./harvestLoss.js";

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test("tons lost is the gap to a full harvest", () => {
  // 0.95 tons at 95% of full means a full harvest of 1.0 ton: 0.05 lost.
  near(lostTons(0.95, 0.95), 0.05);
  assert.equal(lostTons(1.2, 1), 0);
  assert.equal(lostTons(null, 0.9), null);
  assert.equal(lostTons(1, 0), null);
  assert.equal(lostTons(1, undefined), null);
});

test("cause comes from the year's FAO-33 water loss and heat penalty", () => {
  const base = { ky: 0.8, etc_active_mm: 1000, eta_active_mm: 1000, heat_penalty_fraction: 0 };
  assert.equal(lossCause({ ...base, heat_penalty_fraction: 0.02 }), "heat");
  assert.equal(lossCause({ ...base, eta_active_mm: 900 }), "water");
  assert.equal(lossCause({ ...base, eta_active_mm: 900, heat_penalty_fraction: 0.02 }), "both");
  assert.equal(lossCause(base), "none");
  assert.equal(lossCause(null), "unknown");
});

test("hover sentence in plain words and real units, no percent", () => {
  const s = harvestSentence({
    year: 2021, tons: 0.95, relativeYield: 0.95, unit: "tons", perAcre: true, cause: "heat",
  });
  assert.equal(s, "2021: 0.950 tons/acre. That's 0.050 tons/acre less than a full harvest, lost to heat.");
  assert.doesNotMatch(s, /%/);
  assert.equal(
    harvestSentence({ year: 2021, tons: 0.95, relativeYield: 0.95, unit: "lb", perAcre: true, cause: "water" }),
    "2021: 1,900 lb/acre. That's 100 lb/acre less than a full harvest, lost to not enough water.",
  );
  assert.equal(
    harvestSentence({ year: 2010, tons: 1.2, relativeYield: 1, unit: "tons", perAcre: true, cause: "none" }),
    "2010: 1.200 tons/acre, a full harvest.",
  );
  assert.equal(
    harvestSentence({ year: 2021, name: "Corn", tons: 40, relativeYield: 0.8, unit: "tons", perAcre: false, cause: "both" }),
    "Corn: 40.00 tons. That's 10.00 tons less than a full harvest, lost to heat and not enough water.",
  );
  assert.equal(
    harvestSentence({ year: 2021, tons: 0.9, relativeYield: 0.9, unit: "tons", perAcre: true, cause: "unknown" }),
    "2021: 0.900 tons/acre. That's 0.100 tons/acre less than a full harvest, lost to heat or not enough water.",
  );
  assert.equal(harvestSentence({ year: 2021, tons: null, unit: "tons", perAcre: true }), "2021: no harvest estimate.");
});

test("farm average lost per acre adds crops, divides by their acres, averages years", () => {
  const result = {
    years: [2001, 2002],
    blocks: [{ id: "a", acres: 10 }, { id: "b", acres: 30 }, { id: "c", acres: 5 }],
    yield_weight: [
      { block_id: "a", yearly: [{ year: 2001, tons: 9, relative_yield: 0.9 }, { year: 2002, tons: 10, relative_yield: 1 }] },
      { block_id: "b", yearly: [{ year: 2001, tons: 30, relative_yield: 1 }, { year: 2002, tons: 24, relative_yield: 0.8 }] },
    ],
  };
  // 2001: 1 ton lost on 40 acres; 2002: 6 tons lost on 40 acres. Block c has no weight.
  near(averageLostPerAcre(result), (1 / 40 + 6 / 40) / 2);
  assert.equal(averageLostPerAcre({ years: [2001], blocks: [] }), null);
});

test("detail lookup tolerates a missing calculation_details", () => {
  assert.equal(detailFor({}, "a", 2001), null);
  const r = { calculation_details: { blocks: [{ id: "a", yearly: [{ year: 2001, ky: 1 }] }] } };
  assert.deepEqual(detailFor(r, "a", 2001), { year: 2001, ky: 1 });
});

test("loss info table reproduces the card from harvest, relative yield and acres", () => {
  const result = { years: [2020, 2021], blocks: [{ id: "a", crop: "corn", acres: 10 }],
    yield_weight: [{ block_id: "a", yearly: [
      { year: 2020, tons: 8, relative_yield: 0.8 },
      { year: 2021, tons: 9, relative_yield: 0.9 },
    ] }] };
  const record = harvestLossRecord(result);
  const yearly = result.years.map(year => {
    const [harvest, relative, acres] = record.inputs.filter(i => i.source_year === year).map(i => i.value);
    return (harvest / relative - harvest) / acres;
  });
  near(record.value, yearly.reduce((a, b) => a + b) / yearly.length);
  near(record.value, 0.15);
  assert.equal(record.inputs.length, 6);
  assert.equal(harvestLossRecord({}), null);
});
