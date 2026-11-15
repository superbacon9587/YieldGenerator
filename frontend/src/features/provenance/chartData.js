// The one data selector behind every chart and the table under it.
//
//   const data = getChartRows(response, { chart, scope, perAcre, unit });
//   chart:   "yield" | "water" | "profit" | "production"
//   scope:   "farm" or a crop entry (block) id
//   perAcre: per acre values instead of totals (yield chart only)
//   unit:    "tons" or "lb" for harvest
//
// data.rows feed both the chart bars and the table rows; data.average is the table's
// Average row. Values are already rounded the way they are displayed, with the same
// rules as backend/calculations.py table_series (half-up rounding, sums of decimals
// snapped to 6 decimals), so a chart bar, its table cell, and the backend calculation
// record are the same number.
import { CROPS } from "../../domain.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
export const LB_PER_TON = 2000;
export const METRICS = ["harvest", "sales", "cost", "margin", "water", "yield"];

/** Half-up decimal rounding of the shortest decimal form, like backend/rounding.py rnd. */
export function rnd(x, d = 0) {
  if (!finite(x)) return null;
  const s = Math.abs(x).toString();
  let out;
  if (/e/i.test(s)) {
    out = Math.round(Math.abs(x) * 10 ** d) / 10 ** d;
  } else {
    const [whole, frac = ""] = s.split(".");
    if (frac.length <= d) return x + 0;
    let n = BigInt(whole + frac.slice(0, d));
    if (frac.charCodeAt(d) - 48 >= 5) n += 1n;
    const str = n.toString().padStart(d + 1, "0");
    out = Number(d ? `${str.slice(0, -d)}.${str.slice(-d)}` : str);
  }
  return x < 0 && out !== 0 ? -out : out;
}

/** Sum of decimal numbers as a person adds them (float sum snapped to 6 decimals). */
export const exactSum = (values) => rnd(values.reduce((a, b) => a + b, 0), 6);

/** Display decimals for each column (harvest depends on unit and basis). */
export function decimals(metric, { perAcre = false, unit = "tons" } = {}) {
  if (metric === "harvest") return unit === "lb" ? 0 : perAcre ? 3 : 2;
  if (metric === "water") return perAcre ? 2 : 1;
  if (metric === "yield" || metric === "marginPct") return 1;
  return 0;
}

const weightRows = (response) =>
  new Map((response?.yield_weight ?? []).map((w) => [w.block_id, w]));
const rowOf = (entry, year) => entry?.yearly?.find((r) => r.year === year) ?? null;

/** Rows in tons, rounded like the backend table (before any pound conversion). */
function tonsRows(response, scope, perAcre) {
  const blocks = response?.blocks ?? [];
  const weights = weightRows(response);
  const put = (year, harvest, sales, cost, water, ry, parts) => ({
    year,
    harvest,
    sales,
    cost,
    margin: finite(sales) && finite(cost) ? sales - cost : null,
    water,
    yield: rnd(ry * 100, 1),
    parts,
  });
  if (scope === "farm") {
    const totalAcres = exactSum(blocks.map((b) => b.acres));
    return (response?.farm_totals ?? []).map((t) => {
      const known = blocks
        .map((b) => ({ b, w: rowOf(weights.get(b.id), t.year) }))
        .filter(({ w }) => finite(w?.tons));
      const h = known.length ? rnd(exactSum(known.map(({ w }) => w.tons)), 2) : null;
      const moneyAcres = exactSum(
        blocks
          .filter((b) => rowOf(b, t.year)?.profit != null)
          .map((b) => b.acres),
      );
      // Each crop's share of the farm harvest, for stacked bars that add up to the row.
      const parts = Object.fromEntries(known.map(({ b, w }) => [b.id, h ? w.tons / h : 0]));
      const water = Object.fromEntries(blocks.map((b) => [b.id, rowOf(b, t.year)?.water_applied_af ?? null]));
      if (!perAcre)
        return put(t.year, h, t.revenue ?? null, t.cost ?? null, t.water_applied_af, t.relative_yield, { harvest: parts, water });
      const hAcres = exactSum(known.map(({ b }) => b.acres));
      return put(
        t.year,
        finite(h) ? rnd(h / hAcres, 3) : null,
        finite(t.revenue) ? rnd(t.revenue / moneyAcres) : null,
        finite(t.cost) ? rnd(t.cost / moneyAcres) : null,
        rnd(t.water_applied_af / totalAcres, 2),
        t.relative_yield,
        { harvest: parts, water: {} },
      );
    });
  }
  const block = blocks.find((b) => b.id === scope);
  if (!block) return [];
  const w = weights.get(scope);
  return block.yearly.map((r) => {
    const wr = rowOf(w, r.year);
    if (!perAcre)
      return put(r.year, wr?.tons ?? null, r.revenue ?? null, r.cost ?? null, r.water_applied_af, r.relative_yield, {});
    return put(
      r.year,
      wr?.tons_per_acre ?? null,
      finite(r.revenue) ? rnd(r.revenue / block.acres) : null,
      finite(r.cost) ? rnd(r.cost / block.acres) : null,
      rnd(r.water_applied_af / block.acres, 2),
      r.relative_yield,
      {},
    );
  });
}

const label = (block, blocks) => {
  const name = CROPS[block.crop]?.name ?? block.crop;
  return blocks.filter((b) => b.crop === block.crop).length > 1 ? `${name} · ${block.id}` : name;
};

/**
 * Rows, Average row and chart series for one chart view. Each series has a
 * dataKey into the rows. Stacked series add up to row[totalKey].
 */
export function getChartRows(response, view = {}) {
  const { chart = "yield", scope = "farm", perAcre = false, unit = "tons" } = view;
  const opts = { perAcre, unit };
  const blocks = response?.blocks ?? [];
  const drought = new Set(response?.summary?.drought_years ?? []);
  const rows = tonsRows(response, scope, perAcre).map((r) => {
    const harvest = unit === "lb" && finite(r.harvest) ? rnd(r.harvest * LB_PER_TON) : r.harvest;
    const row = {
      year: r.year,
      drought: drought.has(r.year),
      harvest,
      sales: r.sales,
      cost: r.cost,
      margin: r.margin,
      marginPct: finite(r.margin) && finite(r.sales) && r.sales !== 0 ? rnd((r.margin / r.sales) * 100, 1) : null,
      water: r.water,
      yield: r.yield,
    };
    for (const [id, share] of Object.entries(r.parts.harvest ?? {}))
      row[`harvest_${id}`] = finite(harvest) ? harvest * share : null;
    for (const [id, v] of Object.entries(r.parts.water ?? {})) row[`water_${id}`] = v;
    return row;
  });

  const average = {};
  for (const m of ["harvest", "sales", "cost", "water", "yield"]) {
    const v = rows.map((r) => r[m]).filter(finite);
    average[m] = v.length ? rnd(exactSum(v) / v.length, decimals(m, opts)) : null;
  }
  average.margin = finite(average.sales) && finite(average.cost) ? average.sales - average.cost : null;
  average.marginPct =
    finite(average.margin) && finite(average.sales) && average.sales !== 0
      ? rnd((average.margin / average.sales) * 100, 1)
      : null;

  const one = (key) => [{ key, metric: key, label: scope === "farm" ? "Whole farm" : label(blocks.find((b) => b.id === scope) ?? { crop: scope, id: scope }, blocks), color: CROPS[blocks.find((b) => b.id === scope)?.crop]?.color ?? "#4e795d" }];
  let series, totalKey;
  if ((chart === "yield" || chart === "production") && scope === "farm") {
    totalKey = "harvest";
    const weights = weightRows(response);
    series = blocks
      .filter((b) => (weights.get(b.id)?.yearly ?? []).some((r) => finite(r.tons)))
      .map((b) => ({ key: `harvest_${b.id}`, metric: "harvest", label: label(b, blocks), color: CROPS[b.crop]?.color ?? "#557f65", blockId: b.id }));
  } else if (chart === "water" && scope === "farm" && !perAcre) {
    totalKey = "water";
    series = blocks.map((b) => ({ key: `water_${b.id}`, metric: "water", label: label(b, blocks), color: CROPS[b.crop]?.color ?? "#557f65", blockId: b.id }));
  } else {
    totalKey = { yield: "harvest", production: "harvest", water: "water", profit: "margin", cost: "cost" }[chart];
    series = one(totalKey);
  }
  return { view: { chart, scope, perAcre, unit }, rows, average, series, totalKey, stacked: series.length > 1 || series[0]?.key !== totalKey };
}

/** One table or chart value as text, with the column's rounding. */
export function formatCell(metric, value, { perAcre = false, unit = "tons" } = {}) {
  if (!finite(value)) return metric === "marginPct" ? "" : "Not available";
  const d = decimals(metric, { perAcre, unit });
  const n = Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sign = value < 0 && Number(n.replace(/,/g, "")) !== 0 ? "-" : "";
  if (["sales", "cost", "margin"].includes(metric)) return `${sign}$${n}`;
  if (metric === "yield" || metric === "marginPct") return `${sign}${n}%`;
  return `${sign}${n}`;
}

/** Column headers for the table, labelled per acre when the view is per acre. */
export function tableHeaders({ perAcre = false, unit = "tons" } = {}) {
  const w = unit === "lb" ? "lb" : "tons";
  return {
    year: "Year",
    harvest: `Harvest (${w}${perAcre ? "/acre" : ""})`,
    sales: `Sales${perAcre ? " ($/acre)" : ""}`,
    cost: `Cost${perAcre ? " ($/acre)" : ""}`,
    margin: `Margin${perAcre ? " ($/acre)" : ""}`,
    water: `Water (acre-ft${perAcre ? "/acre" : ""})`,
    yield: "Yield (% of potential)",
  };
}

/** Every table cell as text: the rows, then the Average row. */
export function tableCells(data) {
  const v = data.view;
  const cells = (r) => ({
    year: String(r.year ?? "Average"),
    ...Object.fromEntries([...METRICS, "marginPct"].map((m) => [m, formatCell(m, r[m], v)])),
  });
  return { rows: data.rows.map(cells), average: { ...cells(data.average), year: "Average" } };
}

/** The plotted value of a row: the bar, or the top of a stack (sum of its parts). */
export function plottedTotal(data, row) {
  const vals = data.series.map((s) => row[s.key]).filter(finite);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0);
}

/** Id of the backend calculation record behind an Average row cell. */
export const tableRecordId = (scope, perAcre, metric) =>
  `table.${scope}.${perAcre ? "per_acre" : "total"}.${metric === "marginPct" ? "margin_pct" : metric}`;

/** Presentation only: selecting columns never changes the shared rows or averages. */
export function chartGuide(view) {
  const {chart,scope,perAcre,unit="tons"}=view;
  const harvest = "Harvest per acre(year) = baseline yield per acre × relative yield(year) ÷ median relative yield";
  const guides={
    yield:{columns:["harvest","yield"],formula:perAcre?harvest:`${harvest}; total harvest(year) = harvest per acre(year) × acres`,sources:"USDA NASS reference yields; NASA POWER weather and crop-model parameters for relative yield."},
    production:{columns:["harvest"],formula:`${harvest}; total harvest(year) = harvest per acre(year) × acres`,sources:"USDA NASS reference yields; NASA POWER weather and crop-model parameters."},
    water:{columns:["water"],formula:"Applied water(year) = net irrigation need(year) ÷ irrigation efficiency × acres ÷ 304.8 (net need in mm; result in acre-feet)",sources:"NASA POWER weather, FAO-56 water balance, and stored soil, crop and irrigation assumptions."},
    profit:{columns:["sales","cost","margin"],formula:"Operating margin(year) = sales(year) − operating cost(year)",sources:"USDA NASS yields and selling prices; UC Davis cost-study extracts; NASA POWER water modeling; EIA electricity references and water-price assumptions."},
    cost:{columns:["water","cost"],formula:"Operating cost(year) = acres × non-water operating cost per acre + surface-water expense(year) + pumping electricity expense(year)",sources:"UC Davis operating-cost study extracts; modeled water use from NASA POWER; EIA electricity prices and stored surface-water/pumping assumptions."},
  };
  const guide=guides[chart] ?? guides.yield;
  const notes=[];
  if(scope==="farm" && chart!=="profit") notes.push("Whole-farm harvest, water and cost totals sum the included crop entries.");
  if(scope==="farm" && perAcre) notes.push("Per-acre results divide each total by the acreage with data for that metric.");
  if(["yield","production"].includes(chart)) notes.push(`Yield is converted to ${unit==="lb"?"pounds":"US tons"}; one US ton = 2,000 lb.`);
  if(chart==="yield") notes.push("Yield % is modeled relative yield × 100.");
  if(chart==="cost") notes.push("Water expense uses applied water split between surface water and groundwater, priced at the stored rate and pumping electricity cost.");
  notes.push(chart === "profit" ? "Average sales/cost = sum of available yearly values ÷ years with data; average margin = average sales − average cost. Missing values stay unavailable." : "Average = sum of available yearly values ÷ years with data. Missing values stay unavailable.");
  return {...guide,notes:notes.join(" ")};
}
