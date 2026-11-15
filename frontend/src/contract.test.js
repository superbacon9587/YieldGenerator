import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_FARM, clone, toSimulateRequest } from "./domain.js";
import { compareSetups } from "./api.js";
import { SETUPS_KEY, addSetup, loadSetups, setupFormFarm } from "./features/compare/savedSetups.js";

const CONTRACT_KEYS = ["location", "years", "price_mode", "blocks", "optional", "available_acres"];
const BLOCK_KEYS = ["id", "crop", "acres", "irrigation", "start_month", "end_month"];
const OPTIONAL_KEYS = ["soil", "budget_usd", "water_available_af", "water_applied_af", "surface_water_share"];

function optimizeFarm() {
  const farm = clone(DEFAULT_FARM);
  farm.period = "20";
  farm.optimize = { objective: "profit", allowed_crops: ["corn"] };
  farm.blocks[0].displayUnit = "sqft";
  farm.optional.extra_ui = true;
  return farm;
}

function assertClean(req) {
  assert.deepEqual(Object.keys(req).sort(), [...CONTRACT_KEYS].sort());
  for (const b of req.blocks) assert.deepEqual(Object.keys(b).sort(), [...BLOCK_KEYS].sort());
  for (const k of Object.keys(req.optional)) assert.ok(OPTIONAL_KEYS.includes(k), k);
  assert.deepEqual(Object.keys(req.location).sort(), ["label", "lat", "lon"]);
}

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
  };
}

test("a farm with period and optimize fields produces a request with neither", () => {
  const req = toSimulateRequest(optimizeFarm());
  assert.equal("period" in req, false);
  assert.equal("optimize" in req, false);
  assert.equal("extra_ui" in req.optional, false);
  assertClean(req);
  assert.deepEqual(req.years, [2000, 2024]);
});

test("a stored period preset becomes years when years are missing", () => {
  const farm = optimizeFarm();
  delete farm.years;
  const meta = { first_year: 1985, last_full_year: 2025 };
  assert.deepEqual(toSimulateRequest(farm, meta).years, [2006, 2025]);
  const last = new Date().getFullYear() - 1;
  assert.deepEqual(toSimulateRequest(farm).years, [last - 19, last]);
  assert.equal("period" in toSimulateRequest(farm), false);
});

test("the request is the same when cleaned twice", () => {
  const once = toSimulateRequest(optimizeFarm());
  assert.deepEqual(toSimulateRequest(once), once);
});

test("compare sends clean configs, even for setups saved with UI fields", async () => {
  const original = globalThis.fetch;
  let sent;
  globalThis.fetch = async (path, options) => {
    sent = { path, body: JSON.parse(options.body) };
    return { ok: true, json: async () => ({ results: [], ranked_by: "avg_profit" }) };
  };
  try {
    const legacy = { name: "Old optimize plan", farm: optimizeFarm() };
    const other = { name: "Plain", farm: clone(DEFAULT_FARM) };
    await compareSetups([legacy, other], "avg_profit", { mock: false });
  } finally {
    globalThis.fetch = original;
  }
  assert.equal(sent.path, "/api/compare");
  assert.deepEqual(Object.keys(sent.body).sort(), ["configs", "ranked_by"]);
  assert.equal(sent.body.configs.length, 2);
  for (const c of sent.body.configs) {
    assert.deepEqual(Object.keys(c).sort(), ["farm", "name"]);
    assertClean(c.farm);
  }
});

test("saving keeps UI fields next to the farm, not inside it", () => {
  const [entry] = addSetup([], { name: "Plan", farm: optimizeFarm() });
  assertClean(entry.farm);
  assert.equal(entry.ui.period, "20");
  assert.deepEqual(entry.ui.optimize.allowed_crops, ["corn"]);
  const form = setupFormFarm(entry);
  assert.equal(form.period, "20");
  assert.equal(form.optimize.objective, "profit");
});

test("old saved setups are migrated once on load", () => {
  const storage = memoryStorage();
  const old = { name: "Old", farm: optimizeFarm(), saved_at: "2026-11-01T00:00:00.000Z", summary_stats: null };
  storage.setItem(SETUPS_KEY, JSON.stringify([old]));
  const [s] = loadSetups(storage);
  assertClean(s.farm);
  assert.equal(s.ui.period, "20");
  const stored = JSON.parse(storage.getItem(SETUPS_KEY));
  assertClean(stored[0].farm);
  assert.equal(stored[0].ui.optimize.objective, "profit");
  let writes = 0;
  const counting = { getItem: storage.getItem, setItem: (k, v) => { writes++; storage.setItem(k, v); } };
  loadSetups(counting);
  assert.equal(writes, 0);
});
