// Reads the yield_weight part of a /api/simulate response. Every helper
// tolerates a missing or partial yield_weight (older backends, demo data).
import { CROPS } from "../../domain.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);

/** Map of block id to its yield_weight entry. Empty when the field is missing. */
export function weightByBlock(result) {
  const list = Array.isArray(result?.yield_weight) ? result.yield_weight : [];
  return new Map(list.filter((w) => w?.block_id).map((w) => [w.block_id, w]));
}

export const hasWeight = (entry) =>
  Array.isArray(entry?.yearly) &&
  entry.yearly.some((r) => finite(r?.tons_per_acre));

/** The yield_weight row for one block and year, or null. */
export const weightRow = (entry, year) =>
  entry?.yearly?.find((r) => r?.year === year) ?? null;

/** "Corn", or "Corn · b3" when two blocks grow the same crop. */
export function blockLabel(block, blocks) {
  const name = CROPS[block.crop]?.name ?? block.crop;
  return blocks.filter((b) => b.crop === block.crop).length > 1
    ? `${name} · ${block.id}`
    : name;
}

/** Same crop color for every block of a crop, slightly lighter for repeats. */
export function blockColor(block, blocks) {
  const repeat = blocks
    .filter((b) => b.crop === block.crop)
    .findIndex((b) => b.id === block.id);
  return {
    fill: CROPS[block.crop]?.color ?? "#557f65",
    opacity: Math.max(0.45, 1 - 0.25 * Math.max(0, repeat)),
  };
}

/**
 * One chart row per year. For each block id: `${id}` holds the weight in tons
 * (per acre or total) and `${id}__ry` its relative yield. Both are null when
 * the weight is unknown, so no bar and no label are drawn.
 */
export function chartRows(result, blockIds, perAcre) {
  const weights = weightByBlock(result);
  return (result?.years ?? []).map((year) => {
    const row = { year };
    for (const id of blockIds) {
      const r = weightRow(weights.get(id), year);
      const tons = perAcre ? r?.tons_per_acre : r?.tons;
      const known = finite(tons);
      row[id] = known ? tons : null;
      row[`${id}__ry`] =
        known && finite(r?.relative_yield) ? r.relative_yield : null;
    }
    return row;
  });
}

/** Percent labels on bars fit when there are about 20 bars or fewer. */
export const LABEL_BAR_LIMIT = 20;
export const labelsFit = (years, blocks) => years * blocks <= LABEL_BAR_LIMIT;
