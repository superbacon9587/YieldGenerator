// Harvest weight units and formatting. Pure functions, no React.
export const LB_PER_TON = 2000;
export const YIELD_UNITS = { tons: "Tons", lb: "Pounds" };

const finite = (v) => typeof v === "number" && Number.isFinite(v);

/** Convert a weight in US tons to the chosen unit ("tons" or "lb"). */
export const toUnit = (tons, unit) =>
  finite(tons) ? (unit === "lb" ? tons * LB_PER_TON : tons) : null;

/** "tons/acre", "lb/acre", "tons" or "lb". */
export const unitLabel = (unit, perAcre) =>
  `${unit === "lb" ? "lb" : "tons"}${perAcre ? "/acre" : ""}`;

// Same precision as the data tables and calculation records (chartData.js decimals).
const digitsFor = (unit, perAcre) => (unit === "lb" ? 0 : perAcre ? 3 : 2);

/** Number only, for axis ticks and big summary numbers. */
export function formatWeightNumber(tons, unit, perAcre = false) {
  const v = toUnit(tons, unit);
  if (v == null) return null;
  const d = digitsFor(unit, perAcre);
  return v.toLocaleString("en-US", {
    maximumFractionDigits: d,
    minimumFractionDigits: d,
  });
}

/** Short axis tick: 7,200,000 becomes "7.2M", 45,000 "45k", 44.48 "44.48". */
export function formatAxisTick(tons, unit) {
  const v = toUnit(tons, unit);
  if (v == null) return "";
  const a = Math.abs(v);
  const trim = (x) => String(Number(x.toFixed(1)));
  if (a >= 1e6) return `${trim(v / 1e6)}M`;
  if (a >= 1e4) return `${trim(v / 1e3)}k`;
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** "1.16 tons/acre", "34,800 lb", or "No yield data". */
export function formatWeight(tons, unit, perAcre = false) {
  const n = formatWeightNumber(tons, unit, perAcre);
  return n == null ? "No yield data" : `${n} ${unitLabel(unit, perAcre)}`;
}

/** Relative yield as a whole percent: 0.934 becomes "93%". */
export const potentialPercent = (ry) =>
  finite(ry) ? `${Math.round(ry * 100)}%` : null;

/** "1.16 tons/acre, 93% of potential". */
export function weightWithPotential(tons, ry, unit, perAcre) {
  const pct = potentialPercent(ry);
  return `${formatWeight(tons, unit, perAcre)}${pct ? `, ${pct} of potential` : ""}`;
}

const median = (values) => {
  const v = values.filter(finite).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};

/**
 * Same rule as backend/yield_weight.py: scale the baseline tons per acre by
 * relative_yield / median relative_yield of the block. Used by the demo data.
 */
export function scaleToTons(baseTonsPerAcre, relativeYields) {
  const typical = median(relativeYields);
  if (!finite(baseTonsPerAcre) || !typical)
    return relativeYields.map(() => null);
  return relativeYields.map((ry) =>
    finite(ry) ? (baseTonsPerAcre * ry) / typical : null,
  );
}
