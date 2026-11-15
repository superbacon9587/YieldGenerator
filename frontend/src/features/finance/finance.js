import { CROPS } from "../../domain.js";
export const EXPENSES = [
  {
    key: "production",
    label: "Regional non-water production costs",
    color: "#8b8460",
  },
  { key: "surface", label: "Surface water", color: "#6e9fa0" },
  { key: "groundwater", label: "Groundwater pumping", color: "#345d6d" },
];
export const fieldFor = (mode) =>
  mode === "sales" ? "revenue" : mode === "cost" ? "cost" : "profit";
export function financialYear(result, year) {
  const totals = result.farm_totals.find((r) => r.year === Number(year)) ?? {};
  const entries = result.blocks.map((block) => {
    const row = block.yearly.find((r) => r.year === Number(year)) ?? {};
    const audit = result.calculation_details?.blocks.find(
      (b) => b.id === block.id,
    );
    return {
      ...block,
      name: CROPS[block.crop]?.name ?? block.crop,
      row,
      trace: audit?.yearly.find((r) => r.year === Number(year)),
      sources: audit?.sources ?? [],
    };
  });
  return { totals, entries };
}
export function expenseTotals(entries) {
  const included = entries.filter((e) => e.row.cost != null);
  if (
    !included.length ||
    included.some(
      (e) =>
        !e.trace ||
        [
          e.trace.production_cost_excl_water,
          e.trace.surface_water_cost,
          e.trace.groundwater_cost,
        ].some((v) => v == null),
    )
  )
    return null;
  return included.reduce(
    (a, e) => ({
      production: a.production + e.trace.production_cost_excl_water,
      surface: a.surface + e.trace.surface_water_cost,
      groundwater: a.groundwater + e.trace.groundwater_cost,
    }),
    { production: 0, surface: 0, groundwater: 0 },
  );
}
export function financialRows(result, mode, grouping = "crop") {
  const field = fieldFor(mode);
  return result.years.map((year) => {
    const { totals, entries } = financialYear(result, year);
    const expense =
      mode === "cost" && grouping === "expense" ? expenseTotals(entries) : null;
    return {
      year,
      net: totals[field] ?? null,
      ...Object.fromEntries(entries.map((e) => [e.id, e.row[field] ?? null])),
      ...(expense ?? {}),
    };
  });
}
export function cropSeries(result, mode) {
  const field = fieldFor(mode);
  return result.blocks
    .filter((b) => b.yearly.some((r) => r[field] != null))
    .map((b) => ({
      key: b.id,
      label: `${CROPS[b.crop]?.name ?? b.crop} · ${b.id}`,
      color: CROPS[b.crop]?.color ?? "#4e795d",
    }));
}
export function roundingDifference(entries, total, field) {
  if (total == null) return null;
  return total - entries.reduce((s, e) => s + (e.row[field] ?? 0), 0);
}
