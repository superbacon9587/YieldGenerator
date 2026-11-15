import test from "node:test";
import assert from "node:assert/strict";
import {
  SETUPS_KEY,
  addSetup,
  bestValue,
  loadSetups,
  persistSetups,
  rankLocally,
  removeSetup,
  setupAcres,
  setupCrops,
} from "./savedSetups.js";
import { DEFAULT_FARM, clone } from "../../domain.js";

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
  };
}

test("setups save under yg_saved_setups with name, farm, ui, saved_at, summary_stats", () => {
  const storage = memoryStorage();
  const now = new Date("2026-11-14T12:00:00Z");
  const list = addSetup([], { name: "  Today ", farm: DEFAULT_FARM, summary_stats: { avg_profit: 1 } }, now);
  assert.ok(persistSetups(list, storage));
  const raw = JSON.parse(storage.getItem(SETUPS_KEY));
  assert.deepEqual(Object.keys(raw[0]), ["name", "farm", "ui", "saved_at", "summary_stats"]);
  assert.equal(raw[0].name, "Today");
  assert.equal(raw[0].saved_at, "2026-11-14T12:00:00.000Z");
  assert.deepEqual(loadSetups(storage), raw);
});

test("same name replaces, delete removes, and the farm is copied", () => {
  const farm = clone(DEFAULT_FARM);
  let list = addSetup([], { name: "A", farm });
  list = addSetup(list, { name: "B", farm });
  list = addSetup(list, { name: "A", farm: { ...farm, available_acres: 99 } });
  assert.deepEqual(list.map((s) => s.name), ["B", "A"]);
  assert.equal(list[1].farm.available_acres, 99);
  farm.blocks[0].acres = 1;
  assert.equal(list[0].farm.blocks[0].acres, 40);
  assert.deepEqual(removeSetup(list, "B").map((s) => s.name), ["A"]);
});

test("broken storage never crashes", () => {
  const bad = { getItem: () => "{not json", setItem: () => { throw new Error("full"); } };
  assert.deepEqual(loadSetups(bad), []);
  assert.equal(persistSetups([], bad), false);
  const junk = memoryStorage();
  junk.setItem(SETUPS_KEY, JSON.stringify([{ name: "" }, { name: "ok", farm: { blocks: [] } }]));
  assert.deepEqual(loadSetups(junk).map((s) => s.name), ["ok"]);
});

test("card text: crops and acres", () => {
  assert.equal(setupCrops(DEFAULT_FARM), "Almonds, Oats, Corn");
  assert.equal(setupAcres(DEFAULT_FARM), 70);
  const noAcres = { blocks: DEFAULT_FARM.blocks };
  assert.equal(setupAcres(noAcres), 70);
});

test("best value per column, lowest for water", () => {
  assert.equal(bestValue([1, null, 5]), 5);
  assert.equal(bestValue([200, 150, null], true), 150);
  assert.equal(bestValue([null]), null);
});

test("demo ranking follows the backend rules", () => {
  const e = (name, v) => ({ name, summary_stats: { avg_profit: v, avg_water_applied_af: v } });
  const ranked = rankLocally([e("a", 10), e("b", 30), e("c", null), e("d", 30)], "avg_profit");
  assert.deepEqual(ranked.map((r) => [r.name, r.rank]), [["b", 1], ["d", 1], ["a", 3], ["c", 4]]);
  const water = rankLocally([e("a", 200), e("b", 150)], "avg_water_applied_af");
  assert.deepEqual(water.map((r) => r.name), ["b", "a"]);
});
