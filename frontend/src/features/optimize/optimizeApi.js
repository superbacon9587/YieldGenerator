// POST /api/optimize, with plain messages for each way it can fail.
import { USE_MOCK } from "../../api.js";
import { demoOptimize } from "./optimizePlan.js";

const STATUSES = new Set(["optimal", "feasible", "no_profitable_plan", "infeasible", "error"]);

export class OptimizeError extends Error {}

/** Check the response shape so the page never renders a half-formed plan. */
export function checkResponse(body) {
  if (!body || !STATUSES.has(body.status) || !Array.isArray(body.assumptions))
    throw new OptimizeError(
      "The optimizer response does not match the API contract (docs/api_contract.md, POST /api/optimize).",
    );
  if (["optimal", "feasible"].includes(body.status)) {
    const p = body.plan;
    if (!p || !Array.isArray(p.blocks) || !p.blocks.length || !p.summary_stats)
      throw new OptimizeError("The optimizer returned a plan without blocks or summary numbers.");
  }
  return {
    ...body,
    alternatives: body.alternatives ?? [],
    binding_constraints: body.binding_constraints ?? [],
  };
}

/** Error text for a failed HTTP response. Exported for tests. */
export function failureMessage(status, body) {
  if (status === 404 || status === 405)
    return "This backend has no optimizer yet (POST /api/optimize was not found). Update the backend to a version with the Optimize endpoint. Demo mode in the top bar shows a sample plan.";
  if (status === 422) {
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((e) => `${(e.loc ?? []).filter((x) => x !== "body").join(".")}: ${e.msg}`).join("; ")
      : body?.detail;
    return `The optimizer could not use these inputs. ${detail || "Check the location, years, and crop entries."}`;
  }
  if (status === 502) return `A data service the optimizer needs did not respond. ${body?.detail ?? ""}`.trim();
  return `The optimizer request failed (${status}). ${body?.detail ?? ""}`.trim();
}

export async function optimize(request, { mock = USE_MOCK, timeoutMs = 300000 } = {}) {
  if (mock) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    return checkResponse(demoOptimize(request));
  }
  let response;
  try {
    response = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    throw new OptimizeError(
      error.name === "TimeoutError"
        ? "The optimizer did not finish within 5 minutes. Fewer backtest years or fewer allowed crops make the search shorter."
        : "Cannot reach the backend. In the project folder, run: python -m uvicorn backend.api:app --reload. Keep that window open, or select Demo mode for a sample plan.",
    );
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    if (response.ok) throw new OptimizeError("The optimizer did not return JSON.");
  }
  if (!response.ok) throw new OptimizeError(failureMessage(response.status, body));
  return checkResponse(body);
}
