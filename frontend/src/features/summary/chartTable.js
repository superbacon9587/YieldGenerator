// Rows for the data table under each chart. Same rules as table_series in
// backend/calculations.py, so the Average row matches its calculation record.
import { weightByBlock, weightRow } from "../yield/yieldData.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const sum = (values) => values.reduce((a, b) => a + b, 0);
const per = (v, acres) => (finite(v) && acres ? v / acres : null);

export const TABLE_METRICS = ["harvest", "sales", "cost", "margin", "water", "yield"];

/**
 * One row per year: {year, harvest (tons or tons/acre), sales, cost, margin,
 * marginPct, water (acre-ft or acre-ft/acre), yield (percent of full potential)}.
 * scope is "farm" or a block id. Unknown values are null.
 */
export function tableRows(result, scope, perAcre) {
  const blocks = result?.blocks ?? [];
  const weights = weightByBlock(result);
  const withPct = (row) => ({
    ...row,
    marginPct:
      finite(row.margin) && finite(row.sales) && row.sales !== 0
        ? (100 * row.margin) / row.sales
        : null,
  });
  if (scope === "farm") {
    const totalAcres = sum(blocks.map((b) => b.acres));
    return (result?.farm_totals ?? []).map((t) => {
      const known = blocks
        .map((b) => [b, weightRow(weights.get(b.id), t.year)])
        .filter(([, r]) => finite(r?.tons));
      const harvest = known.length ? sum(known.map(([, r]) => r.tons)) : null;
      const harvestAcres = sum(known.map(([b]) => b.acres));
      const moneyAcres = sum(
        blocks
          .filter((b) => b.yearly.find((r) => r.year === t.year)?.profit != null)
          .map((b) => b.acres),
      );
      return withPct({
        year: t.year,
        harvest: perAcre ? per(harvest, harvestAcres) : harvest,
        sales: perAcre ? per(t.revenue, moneyAcres) : (t.revenue ?? null),
        cost: perAcre ? per(t.cost, moneyAcres) : (t.cost ?? null),
        margin: perAcre ? per(t.profit, moneyAcres) : (t.profit ?? null),
        water: perAcre ? per(t.water_applied_af, totalAcres) : t.water_applied_af,
        yield: finite(t.relative_yield) ? t.relative_yield * 100 : null,
      });
    });
  }
  const block = blocks.find((b) => b.id === scope);
  if (!block) return [];
  const div = perAcre ? block.acres : 1;
  return block.yearly.map((r) => {
    const w = weightRow(weights.get(scope), r.year);
    const tons = perAcre ? w?.tons_per_acre : w?.tons;
    return withPct({
      year: r.year,
      harvest: finite(tons) ? tons : null,
      sales: per(r.revenue, div),
      cost: per(r.cost, div),
      margin: per(r.profit, div),
      water: per(r.water_applied_af, div),
      yield: finite(r.relative_yield) ? r.relative_yield * 100 : null,
    });
  });
}

/** Mean of each column over the years that have a value; margin percent from the means. */
export function averageRow(rows) {
  const out = {};
  for (const m of TABLE_METRICS) {
    const v = rows.map((r) => r[m]).filter(finite);
    out[m] = v.length ? sum(v) / v.length : null;
  }
  out.marginPct =
    finite(out.margin) && finite(out.sales) && out.sales !== 0
      ? (100 * out.margin) / out.sales
      : null;
  return out;
}

/** Id of the calculation record behind an Average row cell. */
export const tableRecordId = (scope, perAcre, metric) =>
  `table.${scope}.${perAcre ? "per_acre" : "total"}.${metric}`;
