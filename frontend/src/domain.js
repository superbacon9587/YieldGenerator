export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
export const CROPS = {
  almonds: { name: "Almonds", color: "#af8053", perennial: true },
  walnuts: { name: "Walnuts", color: "#827149", perennial: true },
  processing_tomatoes: { name: "Processing tomatoes", color: "#c96748" },
  corn: { name: "Corn", color: "#c9a349" },
  oats: { name: "Oats", color: "#8a9a62" },
  alfalfa_hay: { name: "Alfalfa", color: "#438876", perennial: true },
};
export const IRRIGATION = {
  drip: "Drip",
  micro_sprinkler: "Micro-sprinkler",
  sprinkler: "Sprinkler",
  flood: "Flood",
};
export const DEFAULT_FARM = {
  location: { lat: 37.3, lon: -120.48, label: "Merced, California" },
  years: [2000, 2024],
  price_mode: "current",
  blocks: [
    {
      id: "b1",
      crop: "almonds",
      acres: 40,
      irrigation: "drip",
      start_month: 1,
      end_month: 12,
    },
    {
      id: "b2",
      crop: "oats",
      acres: 15,
      irrigation: "sprinkler",
      start_month: 11,
      end_month: 4,
    },
    {
      id: "b3",
      crop: "corn",
      acres: 15,
      irrigation: "flood",
      start_month: 5,
      end_month: 9,
    },
  ],
  optional: {
    soil: "loam",
    water_available_af: null,
    water_applied_af: null,
    surface_water_share: 0.5,
    budget_usd: null,
  },
  available_acres: 70,
  period: "20",
};
export const clone = (x) => structuredClone(x);
export const mean = (values) => {
  const finite = values.filter(
    (x) => typeof x === "number" && Number.isFinite(x),
  );
  return finite.length
    ? finite.reduce((a, b) => a + b, 0) / finite.length
    : null;
};
export const number = (v, d = 0) =>
  v == null || !Number.isFinite(Number(v))
    ? "Not available"
    : Number(v).toLocaleString("en-US", {
        maximumFractionDigits: d,
        minimumFractionDigits: d,
      });
export const money = (v) =>
  v == null
    ? "No price data"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(v);
export const percent = (v) =>
  v == null ? "Not available" : `${number(v * 100, 1)}%`;
export const activeMonth = (m, start, end) =>
  start <= end ? m >= start && m <= end : m >= start || m <= end;
export const toAcres = (value, unit) =>
  unit === "sqft" ? Number(value) / 43560 : Number(value);
const blankToNull = (v) => (v === "" || v == null ? null : Number(v));
const toNum = (v) => (v === "" || v == null ? NaN : Number(v));

/** [first, last] for an N-year preset ending at the last full year. */
export function presetYears(
  preset,
  meta = { first_year: 1985, last_full_year: new Date().getFullYear() - 1 },
) {
  const n = Number(preset);
  const last = meta.last_full_year;
  return [Math.max(meta.first_year, last - n + 1), last];
}

// Top-level farm keys the backend accepts (docs/api_contract.md, Request).
const REQUEST_KEYS = new Set([
  "location",
  "years",
  "price_mode",
  "blocks",
  "optional",
  "available_acres",
]);
const OPTIONAL_KEYS = {
  soil: (v) => v,
  budget_usd: blankToNull,
  water_available_af: blankToNull,
  water_applied_af: blankToNull,
  surface_water_share: toNum,
};

function requestYears(farm, meta) {
  const y = farm.years;
  if (Array.isArray(y) && y.length === 2 && y.every((v) => v !== "" && v != null))
    return y.map(Number);
  const preset = Number(farm.period);
  if (farm.period != null && farm.period !== "custom" && Number.isFinite(preset) && preset > 0)
    return meta ? presetYears(preset, meta) : presetYears(preset);
  return Array.isArray(y) ? y.map(Number) : y;
}

/**
 * The exact POST /api/simulate body for a farm (form state, saved setup, or
 * an older stored farm). Copies only contract fields and drops UI-only ones
 * such as period and optimize, so the strict backend never sees them. A
 * stored period preset becomes years when years are missing.
 */
export function toSimulateRequest(farm, meta) {
  const loc = farm.location ?? {};
  const out = {
    location: {
      lat: toNum(loc.lat),
      lon: toNum(loc.lon),
      ...(loc.label != null ? { label: loc.label } : {}),
    },
    years: requestYears(farm, meta),
    price_mode: farm.price_mode ?? "current",
    blocks: (farm.blocks ?? []).map(
      ({ id, crop, acres, irrigation, start_month, end_month }) => ({
        id,
        crop,
        acres: Number(acres),
        irrigation,
        start_month: Number(start_month),
        end_month: Number(end_month),
      }),
    ),
    optional: {},
    available_acres: blankToNull(farm.available_acres),
  };
  const src = farm.optional ?? {};
  for (const [key, convert] of Object.entries(OPTIONAL_KEYS))
    if (key in src) out.optional[key] = convert(src[key]);
  return out;
}

/** UI-only fields of a farm (anything outside the request contract). */
export function uiFieldsOf(farm) {
  return Object.fromEntries(
    Object.entries(farm ?? {}).filter(([k]) => !REQUEST_KEYS.has(k)),
  );
}

/** Form state to request body. Same function as toSimulateRequest. */
export const requestFromForm = (form) => toSimulateRequest(form);
export function validateFarm(farm) {
  const errors = [];
  const last = new Date().getFullYear() - 1;
  if (
    !farm.location.label?.trim() ||
    !Number.isFinite(farm.location.lat) ||
    !Number.isFinite(farm.location.lon) ||
    Math.abs(farm.location.lat) > 90 ||
    Math.abs(farm.location.lon) > 180
  )
    errors.push("Choose a location with valid latitude and longitude.");
  const wraps = farm.blocks.some(
    (b) => Number(b.start_month) > Number(b.end_month),
  );
  if (
    !farm.years.every(Number.isInteger) ||
    farm.years[0] < (wraps ? 1985 : 1984) ||
    farm.years[1] > last ||
    farm.years[0] > farm.years[1]
  )
    errors.push(
      `Choose years from ${wraps ? 1985 : 1984} to ${last}, with the start before the end. Cross-year crops need the previous year's weather.`,
    );
  if (!farm.blocks.length) errors.push("Add at least one crop block.");
  if (new Set(farm.blocks.map((b) => b.id)).size !== farm.blocks.length)
    errors.push("Crop blocks must have unique IDs.");
  farm.blocks.forEach((b, i) => {
    if (
      !CROPS[b.crop] ||
      !IRRIGATION[b.irrigation] ||
      !Number.isFinite(b.acres) ||
      b.acres <= 0 ||
      b.acres > 1e7 ||
      ![b.start_month, b.end_month].every(
        (m) => Number.isInteger(m) && m >= 1 && m <= 12,
      )
    )
      errors.push(
        `Check crop ${i + 1}: select a crop and irrigation, enter a positive area, and choose valid months.`,
      );
  });
  for (const key of ["water_available_af", "water_applied_af"])
    if (
      farm.optional[key] != null &&
      (!Number.isFinite(farm.optional[key]) || farm.optional[key] < 0)
    )
      errors.push(
        "Water amounts must be zero or a positive number. Leave unknown amounts blank.",
      );
  if (
    farm.available_acres !== undefined &&
    (!Number.isFinite(farm.available_acres) || farm.available_acres <= 0)
  )
    errors.push("Enter your available acreage, more than 0 acres.");
  if (
    farm.optional.budget_usd != null &&
    (!Number.isFinite(farm.optional.budget_usd) || farm.optional.budget_usd < 0)
  )
    errors.push("The yearly budget must be zero or a positive dollar amount.");
  if (
    !Number.isFinite(farm.optional.surface_water_share) ||
    farm.optional.surface_water_share < 0 ||
    farm.optional.surface_water_share > 1
  )
    errors.push("Surface-water share must be between 0 and 100%.");
  return errors;
}
export function validateResponse(result) {
  if (
    !result ||
    !Array.isArray(result.years) ||
    !result.years.length ||
    !result.years.every(Number.isInteger) ||
    !Array.isArray(result.blocks) ||
    !result.blocks.length ||
    !Array.isArray(result.farm_totals) ||
    !result.farm_totals.length ||
    !result.summary ||
    !result.location
  )
    throw new Error(
      "The simulation response does not match the team API contract. Check /api/simulate with Person A.",
    );
  if (result.blocks.some((b) => !Array.isArray(b.yearly) || !b.yearly.length))
    throw new Error("The simulation response is missing yearly crop results.");
  for (const row of [
    ...result.farm_totals,
    ...result.blocks.flatMap((b) => b.yearly),
  ])
    if (
      !Number.isInteger(row.year) ||
      !Number.isFinite(row.water_applied_af) ||
      !Number.isFinite(row.relative_yield)
    )
      throw new Error(
        "The simulation response contains missing or invalid water or yield values.",
      );
  return {
    ...result,
    waste_flags: result.waste_flags ?? [],
    assumptions: result.assumptions ?? [],
  };
}
export function summaryMetrics(result) {
  const rows = result.farm_totals;
  return {
    water: mean(rows.map((r) => r.water_applied_af)),
    yield: mean(rows.map((r) => r.relative_yield)),
    profit: mean(rows.map((r) => r.profit)),
    worstProfit: rows.some((r) => r.profit != null)
      ? Math.min(...rows.filter((r) => r.profit != null).map((r) => r.profit))
      : null,
  };
}
export function scenarioFarm(
  baseline,
  { type, blockId, crop, acres, irrigation, start_month, end_month },
  baselineResult,
) {
  const farm = clone(baseline);
  if (type === "drip")
    farm.blocks = farm.blocks.map((b) => ({ ...b, irrigation: "drip" }));
  else if (type === "water")
    farm.optional.water_available_af =
      0.75 * (summaryMetrics(baselineResult).water ?? 0);
  else
    farm.blocks = farm.blocks.map((b) =>
      b.id === blockId
        ? {
            ...b,
            crop,
            acres: Number(acres),
            irrigation,
            ...(start_month != null
              ? { start_month: Number(start_month) }
              : {}),
            ...(end_month != null ? { end_month: Number(end_month) } : {}),
            ...(CROPS[crop]?.perennial
              ? { start_month: 1, end_month: 12 }
              : {}),
          }
        : b,
    );
  return farm;
}
