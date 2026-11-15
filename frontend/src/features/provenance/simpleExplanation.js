import { CROPS } from "../../domain.js";
import { periodCalculation } from "./audit.js";
const n = (value) =>
  value == null
    ? "unavailable"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });
const cash = (value) =>
  value == null
    ? "unavailable"
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      });
export const METRIC_TITLES = {
  avg_harvest: "Average harvest",
  harvest: "Total harvest",
  harvest_per_acre: "Harvest per acre",
  full_yield: "Full-yield reference",
  relative: "Relative yield",
  avg_relative: "Average relative yield",
  profit: "Operating margin",
  avg_profit: "Average operating margin",
  total_profit: "Total operating margin",
  avg_revenue: "Average sales",
  avg_cost: "Average operating cost",
  cost: "Operating cost",
  revenue: "Sales",
  water: "Water applied",
  avg_water: "Average water applied",
  etc: "Crop water use",
  rain: "Effective rain",
  heat: "Heat days",
  gdd: "Growing degree days",
  ranking: "High and low years",
  summary: "Period summary",
};
const unique = (items) =>
  [...new Map(items.filter((x) => x?.url).map((x) => [x.url, x])).values()].map(
    ({ label, url }) => ({ label, url }),
  );
export function simpleExplanation(result, target, unit = "tons") {
  const data = result.calculation_details;
  const block = data?.blocks.find((b) => b.id === target.blockId);
  const row =
    block?.yearly.find((r) => r.year === Number(target.year)) ??
    (target.metric === "full_yield" ? block?.yearly[0] : null);
  let metric = target.metric;
  if (!block)
    metric =
      {
        profit: "avg_profit",
        harvest: "avg_harvest",
        water: "avg_water",
        relative: "avg_relative",
        summary: "avg_profit",
      }[metric] ?? metric;
  const output = {
    title: METRIC_TITLES[metric] ?? "Calculation",
    scope: block
      ? `${CROPS[block.crop]?.name ?? block.crop} · ${target.year ?? `${result.years[0]}–${result.years.at(-1)}`} · ${block.acres} acres`
      : `${result.years[0]}–${result.years.at(-1)} · selected backtest`,
    formula:
      "Exact calculation inputs are unavailable. Rerun in Live backend mode.",
    origins: [],
    links: [],
    note: "",
  };
  if (!data) return output;
  const multiplier = unit === "lb" ? 2000 : 1,
    weight = unit === "lb" ? "lb" : "US tons";
  const scaled = (value) => (value == null ? null : value * multiplier);
  const baseline = block?.sources?.find((s) =>
    s.label.startsWith("Baseline yield"),
  );
  const costSource = block?.sources?.find((s) =>
    s.label.startsWith("Regional production"),
  );
  const coefficient = block?.sources?.find((s) =>
    s.label.startsWith("Crop coefficients"),
  );
  const cropModel = {
    label: "Our model",
    text: "Uses farm inputs and weather to calculate crop growth and water response; these are estimates, not observed harvests.",
  };
  if (row) {
    const base = {
      label: "Repo CSV",
      text: `${n(row.baseline_yield?.value)} ${row.baseline_yield?.unit ?? ""}. ${row.baseline_yield?.source ?? "No yield reference available."}`,
    };
    const weather = {
      label: "NASA POWER",
      text: `Daily weather for ${row.season_start} to ${row.season_end}; NASA does not supply harvest or sales.`,
    };
    const price = {
      label: "Repo CSV",
      text: `Crop price ${n(row.crop_price?.value)} ${row.crop_price?.unit ?? ""}, reference year ${row.crop_price?.year ?? "unavailable"}.`,
    };
    output.origins = [base, weather, cropModel];
    output.links = unique([baseline, row.weather_source, data.harvest_source]);
    if (metric === "full_yield") {
      output.formula = `${n(scaled(row.baseline_tons_per_acre))} ${weight}/acre ÷ ${n(row.median_relative_yield)} uncapped reference fraction ≈ ${n(row.median_relative_yield && row.baseline_tons_per_acre != null ? scaled(row.baseline_tons_per_acre) / row.median_relative_yield : null)} ${weight}/acre full-yield reference`;
      output.origins = [
        base,
        {
          label: "Our model",
          text: `The denominator is the uncapped-water median over ${result.years[0]}–${result.years.at(-1)} for this crop and calendar. It stays fixed when water is limited.`,
        },
      ];
      output.note =
        "The CSV provides a typical median yield, not full yield. Full yield is a model-derived reference, not a NASA measurement.";
    } else if (metric === "harvest_per_acre" || metric === "harvest") {
      output.formula = `${n(scaled(row.baseline_tons_per_acre))} ${weight}/acre × ${n(row.displayed.relative_yield)} ÷ ${n(row.median_relative_yield)}${metric === "harvest" ? ` × ${n(block.acres)} acres` : ""} ≈ ${n(scaled(metric === "harvest" ? row.harvest_tons : row.harvest_tons_per_acre))} ${weight}${metric === "harvest_per_acre" ? "/acre" : ""}`;
      output.note =
        "CSV baseline × modeled relative yield ÷ the fixed uncapped reference; multiply by your acreage for total harvest. One US ton = 2,000 lb.";
    } else if (["profit", "revenue", "cost"].includes(metric)) {
      output.formula =
        metric === "profit"
          ? `${cash(row.revenue_unrounded)} sales − ${cash(row.cost_unrounded)} operating cost ≈ ${cash(row.profit_unrounded)} margin`
          : metric === "revenue"
            ? `${n(row.sale_quantity)} sale units × ${n(row.crop_price?.value)} ${row.crop_price?.unit ?? ""} ≈ ${cash(row.revenue_unrounded)} sales`
            : `${cash(row.production_cost_per_acre)}/acre × ${n(block.acres)} acres + ${cash(row.water_cost)} modeled water cost ≈ ${cash(row.cost_unrounded)}`;
      output.origins = [
        price,
        {
          label: "Repo CSV",
          text: `Non-water operating cost ${cash(row.production_cost_per_acre)}/acre. ${row.production_cost_source?.source ?? "Cost reference missing."}`,
        },
        weather,
      ];
      output.links = unique([
        row.price_source,
        costSource,
        row.weather_source,
        data.model_source,
      ]);
      output.note =
        "Operating costs are reference estimates, not your expenses; separate overhead and establishment are excluded. A budget is a limit, not an expense input.";
    } else if (metric === "water") {
      output.formula = `${n(row.net_irrigation_applied_mm)} net mm ÷ 304.8 × ${n(block.acres)} acres ÷ ${n(row.irrigation_efficiency)} efficiency ≈ ${n(row.applied_water_unrounded_af)} acre-ft`;
      output.origins = [
        weather,
        {
          label: "Repo JSON + farm inputs",
          text: `Crop/soil coefficients and irrigation efficiency; ${block.acres} acres, ${row.soil} soil.`,
        },
        cropModel,
      ];
      output.links = unique([
        row.weather_source,
        coefficient,
        data.model_source,
      ]);
    } else if (metric === "relative") {
      output.formula = `clip[1 − ${n(row.ky)} × (1 − ${n(row.eta_active_mm)} actual ET ÷ ${n(row.etc_active_mm)} full ET) − ${n(row.heat_penalty_fraction)} heat penalty] ≈ ${n(row.displayed.relative_yield * 100)}%`;
      output.origins = [
        weather,
        {
          label: "Repo JSON",
          text: `Ky = ${n(row.ky)}; crop coefficients and heat threshold come from crops.json, including entries marked for verification.`,
        },
        cropModel,
      ];
      output.links = unique([
        row.weather_source,
        coefficient,
        data.model_source,
      ]);
      output.note =
        "This percentage is modeled relative to an unstressed crop; it is not a USDA-recorded harvest percentage.";
    } else if (metric === "etc" || metric === "rain") {
      output.formula =
        metric === "etc"
          ? `Sum(ET0 × daily crop coefficient) = ${n(row.etc_all_mm)} mm ÷ 25.4 ≈ ${n(row.displayed.crop_water_use_in)} inches`
          : `Sum(modeled effective rain) = ${n(row.effective_rain_mm)} mm ÷ 25.4 ≈ ${n(row.displayed.effective_rain_in)} inches`;
      output.origins = [
        weather,
        {
          label: "Our model",
          text:
            metric === "etc"
              ? "ET0 is calculated from POWER weather using FAO-56; crop coefficients come from repo JSON."
              : "Daily rain below 5 mm is excluded; 80% of larger rain enters the effective-rain term.",
        },
      ];
      output.links = unique([
        row.weather_source,
        coefficient,
        data.model_source,
      ]);
    } else if (metric === "heat" || metric === "gdd") {
      output.formula =
        metric === "heat"
          ? `Count active days with daily maximum > ${n(row.heat_threshold_c)}°C = ${row.displayed.heat_stress_days} heat days`
          : `Sum active days max(0, (daily Tmax + Tmin) ÷ 2 − ${n(row.gdd_base_c)}°C) ≈ ${n(row.displayed.gdd)} °C-days`;
      output.origins = [
        weather,
        {
          label: "Repo JSON",
          text: "The crop temperature threshold/base is from crops.json; some parameters still require verification.",
        },
      ];
      output.links = unique([row.weather_source, coefficient]);
    }
  } else {
    const p = periodCalculation(
      result,
      metric === "avg_harvest"
        ? "harvest"
        : metric === "avg_water"
          ? "water"
          : metric === "avg_relative"
            ? "relative"
            : "profit",
    );
    const rec = data.reconciliation;
    if (metric === "avg_harvest")
      output.formula = `${n(scaled(p.sum))} total modeled ${weight} ÷ ${p.count} included years ≈ ${n(scaled(p.average))} ${weight}/year`;
    else if (metric === "avg_water")
      output.formula = `${n(p.sum)} total modeled acre-ft ÷ ${p.count} years ≈ ${n(p.average)} acre-ft/year`;
    else if (metric === "avg_relative")
      output.formula = `Sum of ${p.count} yearly acre-weighted yield fractions ÷ ${p.count} × 100 ≈ ${n(p.average == null ? null : p.average * 100)}%`;
    else if (metric === "total_profit")
      output.formula = `Sum of the ${p.count} included yearly operating margins = ${cash(p.sum)}`;
    else if (metric === "avg_revenue" || metric === "avg_cost") {
      const key = metric === "avg_revenue" ? "revenue" : "cost";
      const values = result.farm_totals
        .map((r) => r[key])
        .filter((v) => v != null);
      const sum = values.reduce((a, b) => a + b, 0);
      output.formula = `${cash(sum)} total ${key === "revenue" ? "sales" : "operating cost"} ÷ ${values.length} included years ≈ ${cash(values.length ? sum / values.length : null)}/year`;
    } else if (metric === "ranking")
      output.formula = `Highest included yearly margin: ${result.summary.best_year}; lowest: ${result.summary.worst_year}. ${result.assumptions.find((s) => s.includes("years are ranked by")) ?? "Ranking method not provided."}`;
    else
      output.formula = `${cash(rec.avg_revenue)} average sales − ${cash(rec.avg_cost)} average operating cost ≈ ${cash(rec.avg_profit)} average margin/year`;
    output.origins = [
      {
        label: "NASA POWER",
        text: `Weather history for the selected ${result.years[0]}–${result.years.at(-1)} period.`,
      },
      {
        label: "Repo CSVs",
        text: "NASS reference yields and crop prices; regional UC operating-cost extracts.",
      },
      {
        label: "Our model",
        text: "Calculates each crop-year, then sums or averages the included results.",
      },
    ];
    output.links = unique([
      ...data.blocks
        .flatMap((b) => b.sources ?? [])
        .filter(
          (s) =>
            s.label.startsWith("Baseline yield") ||
            s.label.startsWith("Regional production"),
        ),
      data.model_source,
    ]);
    output.note = data.excluded_financial_blocks.length
      ? `Financial totals exclude ${data.excluded_financial_blocks.map((b) => CROPS[b.crop]?.name ?? b.crop).join(", ")} because financial inputs are missing. Harvest and water totals can include those crops.`
      : "These are modeled estimates, not your farm's recorded expenses or income.";
  }
  return output;
}
