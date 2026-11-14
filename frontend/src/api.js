import { generateMock } from "./mock/generate.js";
import { validateResponse } from "./domain.js";
import { FALLBACK_META, summaryOf } from "./features/summary/landBudget.js";
import { rankLocally } from "./features/compare/savedSetups.js";
export const USE_MOCK = import.meta.env?.VITE_USE_MOCK === "true";
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      signal: AbortSignal.timeout(180000),
    });
  } catch (error) {
    throw new Error(
      error.name === "TimeoutError"
        ? "The simulation timed out. Try fewer years or check the backend."
        : "Cannot reach the backend. In the project folder, run: python -m uvicorn backend.api:app --reload. Keep that window open, or select Demo mode for offline samples.",
    );
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(
      "The backend is unavailable or did not return JSON. In the project folder, run: python -m uvicorn backend.api:app --reload. Keep that window open.",
    );
  }
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail
          .map(
            (e) => `${e.loc?.filter((x) => x !== "body").join(".")}: ${e.msg}`,
          )
          .join("; ")
      : body.detail || body.error;
    throw new Error(
      detail ||
        `Request failed (${response.status}). Check the backend endpoint.`,
    );
  }
  return body;
}
export async function simulate(farm, { mock = USE_MOCK } = {}) {
  if (mock) {
    await new Promise((resolve) => setTimeout(resolve, 650));
    return validateResponse(generateMock(farm));
  }
  return validateResponse(
    await request("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(farm),
    }),
  );
}
const places = [
  { label: "Merced, California, United States", lat: 37.3, lon: -120.48 },
  { label: "Fresno, California, United States", lat: 36.7378, lon: -119.7871 },
  {
    label: "Sacramento, California, United States",
    lat: 38.5816,
    lon: -121.4944,
  },
  { label: "Nairobi, Kenya", lat: -1.2833, lon: 36.8167 },
  { label: "New Delhi, India", lat: 28.6139, lon: 77.209 },
  { label: "São Paulo, Brazil", lat: -23.55, lon: -46.6333 },
];
export async function geocode(query, { mock = USE_MOCK } = {}) {
  if (mock) {
    await new Promise((resolve) => setTimeout(resolve, 180));
    return places.filter((p) =>
      p.label.toLowerCase().includes(query.toLowerCase()),
    );
  }
  const response = await request(`/api/geocode?q=${encodeURIComponent(query)}`);
  return Array.isArray(response) ? response : (response.results ?? []);
}

// Part A: backtest period range and saved-setup ranking.

export async function meta({ mock = USE_MOCK } = {}) {
  if (mock) return { ...FALLBACK_META };
  try {
    const m = await request("/api/meta");
    return Number.isInteger(m?.first_year) && Number.isInteger(m?.last_full_year)
      ? { ...FALLBACK_META, ...m }
      : { ...FALLBACK_META };
  } catch {
    return { ...FALLBACK_META }; // older backend without /api/meta
  }
}

export async function compareSetups(configs, rankedBy, { mock = USE_MOCK } = {}) {
  if (mock) {
    const entries = configs.map((c) => {
      const result = generateMock(c.farm);
      return { name: c.name, summary_stats: summaryOf(result), budget: null };
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    return { results: rankLocally(entries, rankedBy), ranked_by: rankedBy };
  }
  return request("/api/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ configs, ranked_by: rankedBy }),
  });
}
