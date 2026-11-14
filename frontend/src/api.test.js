import test from "node:test";
import assert from "node:assert/strict";
import { USE_MOCK, simulate } from "./api.js";
import { DEFAULT_FARM, requestFromForm } from "./domain.js";
test("API defaults to live backend mode", () => assert.equal(USE_MOCK, false));
test("backend connection failure explains Windows startup and never returns demo", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new TypeError("offline");
  };
  try {
    await assert.rejects(
      simulate(requestFromForm(DEFAULT_FARM)),
      /python -m uvicorn backend.api:app --reload/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
