// Saved setups live in localStorage under one key so the Compare page (Part A)
// and the Optimize tab (Part C) share the same list.
import { CROPS } from "../../domain.js";

export const SETUPS_KEY = "yg_saved_setups";
export const MIN_COMPARE = 2;
export const MAX_COMPARE = 6;

const isSetup = (s) =>
  s &&
  typeof s.name === "string" &&
  s.name.trim() &&
  s.farm &&
  Array.isArray(s.farm.blocks);

export function loadSetups(storage = globalThis.localStorage) {
  try {
    const raw = JSON.parse(storage?.getItem(SETUPS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter(isSetup) : [];
  } catch {
    return [];
  }
}

export function persistSetups(setups, storage = globalThis.localStorage) {
  try {
    storage.setItem(SETUPS_KEY, JSON.stringify(setups));
    return true;
  } catch {
    return false;
  }
}

/** Add a setup, replacing one with the same name. Returns the new list. */
export function addSetup(setups, { name, farm, summary_stats = null }, now = new Date()) {
  const clean = name.trim();
  const entry = {
    name: clean,
    farm: structuredClone(farm),
    saved_at: now.toISOString(),
    summary_stats,
  };
  return [...setups.filter((s) => s.name !== clean), entry];
}

export const removeSetup = (setups, name) => setups.filter((s) => s.name !== name);

export function setupCrops(farm) {
  return [...new Set(farm.blocks.map((b) => CROPS[b.crop]?.name ?? b.crop))].join(", ");
}

export function setupAcres(farm) {
  if (farm.available_acres != null) return Number(farm.available_acres);
  return farm.blocks.reduce((s, b) => s + (Number(b.acres) || 0), 0);
}

export const RANK_OPTIONS = {
  avg_profit: "Average operating margin per year",
  total_profit: "Total operating margin",
  avg_relative_yield: "Average relative yield",
  avg_water_applied_af: "Average water per year",
};
export const LOWER_IS_FIRST = new Set(["avg_water_applied_af"]);

/** The value to bold in a column: highest, or lowest for water/overruns. */
export function bestValue(values, lowerFirst = false) {
  const nums = values.filter((v) => v != null && Number.isFinite(v));
  if (!nums.length) return null;
  return lowerFirst ? Math.min(...nums) : Math.max(...nums);
}

/** Local ranking for Demo mode, same rules as POST /api/compare. */
export function rankLocally(entries, rankedBy) {
  const lower = LOWER_IS_FIRST.has(rankedBy);
  const order = entries
    .map((e, i) => ({ e, i, v: e.summary_stats?.[rankedBy] ?? null }))
    .sort((a, b) =>
      a.v == null || b.v == null
        ? (a.v == null) - (b.v == null) || a.i - b.i
        : (lower ? a.v - b.v : b.v - a.v) || a.i - b.i,
    );
  let prev = null;
  return order.map((x, pos) => {
    const rank = prev && prev.v === x.v ? prev.rank : pos + 1;
    prev = { v: x.v, rank };
    return { ...x.e, rank };
  });
}
