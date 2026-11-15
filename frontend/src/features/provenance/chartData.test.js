// Chart and table read one array (getChartRows), checked on the same sample response
// the backend checks in tests/test_cross_checks.py (scripts/make_sample_response.py).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  decimals,
  exactSum,
  formatCell,
  getChartRows,
  plottedTotal,
  rnd,
  tableCells,
  tableRecordId,
} from "./chartData.js";

const sample = JSON.parse(readFileSync(new URL("./sample_response.json", import.meta.url)));
const blockIds = sample.blocks.map((b) => b.id);
const UNITS = ["tons", "lb"];

// Every chart view on the Results page: crop chips, Per acre / Total, Tons / Pounds.
function views() {
  const out = [];
  for (const unit of UNITS) {
    for (const scope of ["farm", ...blockIds])
      for (const perAcre of [false, true]) out.push({ chart: "yield", scope, perAcre, unit });
    for (const chart of ["water", "profit", "cost"])
      for (const scope of ["farm", ...blockIds]) out.push({ chart, scope, perAcre: false, unit });
    for (const scope of blockIds) out.push({ chart: "production", scope, perAcre: false, unit });
  }
  return out;
}
const label = (v) => `${v.chart}/${v.scope}/${v.perAcre ? "per acre" : "total"}/${v.unit}`;
let checks = 0;

test("every plotted value equals its table cell after the same rounding", () => {
  for (const view of views()) {
    const data = getChartRows(sample, view);
    const cells = tableCells(data);
    assert.equal(data.rows.length, sample.years.length, label(view));
    data.rows.forEach((row, i) => {
      const plotted = plottedTotal(data, row);
      const d = decimals(data.totalKey, view);
      const shown = formatCell(data.totalKey, plotted == null ? null : rnd(plotted, d), view);
      assert.equal(shown, cells.rows[i][data.totalKey], `${label(view)} ${row.year}`);
      checks++;
      for (const s of data.series) assert.ok(row[s.key] == null || Number.isFinite(row[s.key]));
    });
  }
});

test("the Average row is the sum of the year rows over the years with data", () => {
  for (const view of views()) {
    const { rows, average } = getChartRows(sample, view);
    for (const m of ["harvest", "sales", "cost", "water", "yield"]) {
      const v = rows.map((r) => r[m]).filter(Number.isFinite);
      assert.equal(average[m], v.length ? rnd(exactSum(v) / v.length, decimals(m, view)) : null, `${label(view)} ${m}`);
      checks++;
    }
    if (average.sales != null) {
      assert.equal(average.margin, average.sales - average.cost);
      const m = rows.map((r) => r.margin).filter(Number.isFinite);
      const before = exactSum(m) / m.length;
      const parts = exactSum(rows.map((r) => r.sales).filter(Number.isFinite)) / m.length -
        exactSum(rows.map((r) => r.cost).filter(Number.isFinite)) / m.length;
      assert.ok(Math.abs(before - parts) < 1e-6, label(view));
      checks += 2;
    }
  }
});

test("Average row cells equal the backend calculation records", () => {
  for (const view of views().filter((v) => v.chart === "yield")) {
    const { average } = getChartRows(sample, view);
    for (const m of ["harvest", "sales", "cost", "margin", "water", "yield", "marginPct"]) {
      const rec = sample.calculations[tableRecordId(view.scope, view.perAcre, m)];
      if (average[m] == null) {
        assert.equal(rec, undefined, `${label(view)} ${m}`);
        continue;
      }
      const value = m === "harvest" && view.unit === "lb" ? rec.lb.value : rec.value;
      assert.equal(average[m], value, `${label(view)} ${m}`);
      checks++;
    }
  }
});

test("margin is sales minus cost and margin percent is margin / sales x 100, on every row", () => {
  for (const view of views()) {
    const { rows, average } = getChartRows(sample, view);
    for (const r of [...rows, average]) {
      if (r.sales == null || r.cost == null) {
        assert.equal(r.margin, null);
        continue;
      }
      assert.equal(r.margin, r.sales - r.cost, `${label(view)} ${r.year}`);
      assert.equal(r.marginPct, r.sales ? rnd((r.margin / r.sales) * 100, 1) : null);
      checks += 2;
    }
  }
});

test("sales equal harvest x the price used that year for every crop row", () => {
  const LB = { LB: 1, TON: 2000, BU: { corn: 56, oats: 32 } };
  for (const b of sample.blocks) {
    const { rows } = getChartRows(sample, { chart: "production", scope: b.id, unit: "tons" });
    for (const r of rows) {
      if (r.sales == null) continue;
      const rec = sample.calculations[`block.${b.id}.${r.year}.profit`];
      const price = rec.inputs.find((i) => / price, \d{4}$/.test(i.name));
      const unit = price.unit.split("/")[1].toUpperCase();
      const qty =
        unit === "TON" ? r.harvest : unit === "LB" ? r.harvest * 2000 : (r.harvest * 2000) / LB.BU[b.crop];
      assert.equal(r.sales, rnd(qty * price.value), `${b.id} ${r.year}`);
      checks++;
    }
  }
});

test("farm rows are the sum of the crop rows", () => {
  for (const unit of UNITS) {
    const farm = getChartRows(sample, { chart: "water", scope: "farm", unit }).rows;
    const crops = blockIds.map((id) => getChartRows(sample, { chart: "water", scope: id, unit }).rows);
    farm.forEach((row, i) => {
      for (const m of ["harvest", "sales", "cost", "margin", "water"]) {
        const v = crops.map((c) => c[i][m]).filter(Number.isFinite);
        const d = decimals(m, { unit });
        assert.equal(row[m], v.length ? rnd(exactSum(v), d) : null, `${unit} ${row.year} ${m}`);
        checks++;
      }
    });
  }
});

test("summary cards equal the whole-farm table", () => {
  const s = sample.summary_stats;
  const { rows, average } = getChartRows(sample, { chart: "profit", scope: "farm", unit: "tons" });
  assert.equal(s.total_profit, exactSum(rows.map((r) => r.margin).filter(Number.isFinite)));
  assert.equal(s.avg_profit, average.margin);
  assert.equal(s.avg_cost, average.cost);
  assert.equal(s.avg_yield_tons, average.harvest);
  assert.equal(s.avg_water_applied_af, average.water);
  const lb = getChartRows(sample, { chart: "yield", scope: "farm", unit: "lb" }).average.harvest;
  assert.equal(sample.calculations["summary.avg_yield_tons"].lb.value, lb);
  checks += 6;
});

test("rounding matches the backend: half up on the decimal digits", () => {
  assert.equal(rnd(2.675, 2), 2.68);
  assert.equal(rnd(1.005, 2), 1.01);
  assert.equal(rnd(-0.5), -1);
  assert.equal(rnd(2500.5), 2501);
  assert.equal(rnd(5.984999999999999 / 6, 3), 0.997);
  assert.equal(rnd(exactSum([0.996, 0.999, 1.001, 1.001, 0.986, 1.002]) / 6, 3), 0.998);
});

test.after(() => console.log(`chart and table checks: ${checks}`));

test("cost bars use annual costs and the average matches the same table rows", () => {
 const data=getChartRows(sample,{chart:"cost",scope:"farm",unit:"tons"});
 assert.equal(data.totalKey,"cost");
 for(const row of data.rows) assert.equal(plottedTotal(data,row),sample.farm_totals.find(y=>y.year===row.year).cost);
 const known=data.rows.map(r=>r.cost).filter(v=>v!=null);
 assert.equal(data.average.cost,rnd(exactSum(known)/known.length));
 const missing={...sample,blocks:sample.blocks.map(b=>({...b,yearly:b.yearly.map(y=>({...y,cost:null}))})),farm_totals:sample.farm_totals.map(y=>({...y,cost:null}))};
 const empty=getChartRows(missing,{chart:"cost",scope:"farm"});
 assert.equal(empty.average.cost,null);
 assert.ok(empty.rows.every(row=>plottedTotal(empty,row)===null));
});

test("graph-specific columns change presentation without changing values", async () => {
 const {chartGuide}=await import("./chartData.js");
 const expected={yield:["harvest","yield"],production:["harvest"],water:["water"],profit:["sales","cost","margin"],cost:["water","cost"]};
 for(const [chart,columns] of Object.entries(expected)) {
  const data=getChartRows(sample,{chart,scope:"farm",unit:"tons"});
  const before=JSON.stringify(data);
  const guide=chartGuide(data.view);
  assert.deepEqual(guide.columns,columns);
  const cells=tableCells(data);
  for(const row of cells.rows) for(const column of columns) assert.equal(row[column],formatCell(column,data.rows.find(r=>r.year===Number(row.year))[column],data.view));
  assert.equal(JSON.stringify(data),before);
  assert.match(guide.formula,/=/);
  assert.ok(guide.sources.length);
 }
});
