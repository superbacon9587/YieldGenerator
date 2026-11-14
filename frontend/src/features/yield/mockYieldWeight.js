// Demo-mode yield_weight and summary_stats, built the same way as
// backend/yield_weight.py. The baselines are illustrative, not NASS data.
import { scaleToTons } from "./yieldUnits.js";

// Typical tons per acre used only by the demo fixture.
const DEMO_TONS_PER_ACRE = {
  almonds: 1.2, // about 2,400 lb / acre
  walnuts: 2.0,
  processing_tomatoes: 48,
  corn: 4.48, // 160 bu x 56 lb / 2000
  oats: 1.28, // 80 bu x 32 lb / 2000
  alfalfa_hay: 7,
};
const round = (v, d) => (v == null ? null : Number(v.toFixed(d)));
const mean = (v) => {
  const f = v.filter((x) => x != null);
  return f.length ? f.reduce((a, b) => a + b, 0) / f.length : null;
};

export function mockYieldWeight(blocks) {
  const yield_weight = blocks.map((b) => {
    const tpa = scaleToTons(
      DEMO_TONS_PER_ACRE[b.crop],
      b.yearly.map((r) => r.relative_yield),
    );
    return {
      block_id: b.id,
      crop: b.crop,
      acres: b.acres,
      source_unit: "TONS / ACRE",
      conversion: "demo baseline",
      yearly: b.yearly.map((r, i) => ({
        year: r.year,
        tons_per_acre: round(tpa[i], 3),
        tons: round(tpa[i] == null ? null : tpa[i] * b.acres, 2),
        relative_yield: r.relative_yield,
      })),
      avg_tons: round(
        mean(tpa.map((t) => (t == null ? null : t * b.acres))),
        2,
      ),
      avg_tons_per_acre: round(mean(tpa), 3),
    };
  });
  const totals = new Map();
  for (const w of yield_weight)
    for (const r of w.yearly)
      if (r.tons != null)
        totals.set(r.year, (totals.get(r.year) ?? 0) + r.tons);
  return {
    yield_weight,
    summary_stats: { avg_yield_tons: round(mean([...totals.values()]), 2) },
  };
}
