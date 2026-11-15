// Calculation records from the backend (backend/calculations.py). Pure helpers, no React.
//   record = {id, label, value, unit, decimals, formula_text, is_estimate,
//             steps: [{text, expr, result}],
//             inputs: [{name, value, unit, source, source_url, links: [{label, url}],
//                       derived_from: [text], source_verified, kind, is_estimate,
//                       estimate_reason, not_estimate_reason}]}
import { LB_PER_TON } from "../yield/yieldUnits.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const WEIGHT_UNITS = new Set(["tons", "tons/acre"]);

/** Publisher pages only: https, never the code repository. */
const publisherLink = (url) =>
  typeof url === "string" && url.startsWith("https://") && !url.includes("github.com");

/**
 * What the Source cell shows for one input: the farmer-readable text, the
 * "From: ..." line for estimates, publisher links, and whether the source has
 * been checked (false shows "Source not yet verified").
 */
export function sourceParts(input) {
  const links = (
    input.links ?? (input.source_url ? [{ label: "Publisher page", url: input.source_url }] : [])
  ).filter((l) => publisherLink(l.url));
  const derived = input.derived_from ?? [];
  return {
    text: input.source,
    from: derived.length ? `From: ${derived.join(", ")}` : null,
    links,
    verified: input.source_verified !== false,
  };
}

const unique = (items, key = (x) => x) => {
  const seen = new Set();
  return items.filter((x) => (seen.has(key(x)) ? false : seen.add(key(x))));
};

/** Number with commas and up to `d` decimals, trailing zeros dropped. */
export function plain(v, d = 2) {
  if (!finite(v)) return "Not available";
  return v.toLocaleString("en-US", { maximumFractionDigits: d });
}

const signedMoney = (v, d = 0) =>
  `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", {
    maximumFractionDigits: d,
    minimumFractionDigits: d,
  })}`;

/** The record's value as the app prints it (money whole dollars, percent 1 decimal). */
export function formatRecordValue(record) {
  if (!record || !finite(record.value)) return "Not available";
  const { value, unit } = record;
  if (unit === "year") return String(value);
  if (unit === "$") return signedMoney(value);
  if (unit === "$/acre") return `${signedMoney(value)}/acre`;
  if (unit === "%") return `${value.toLocaleString("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`;
  if (unit === "tons") return `${plain(value, 1)} tons`;
  if (unit === "tons/acre") return `${plain(value, 2)} tons/acre`;
  if (unit === "lb" || unit === "lb/acre") return `${plain(value, 0)} ${unit}`;
  if (unit === "acre-ft") return `${plain(value, 1)} acre-ft`;
  if (unit === "acre-ft/acre") return `${plain(value, 2)} acre-ft/acre`;
  return `${plain(value, record.decimals ?? 2)}${unit ? ` ${unit}` : ""}`;
}

/**
 * The record in the harvest unit the page shows. Tons become pounds with one
 * extra step, so the popover ends in the number next to the button.
 */
export function inWeightUnit(record, weightUnit) {
  if (!record || weightUnit !== "lb" || !WEIGHT_UNITS.has(record.unit) || !finite(record.value))
    return record;
  // The backend builds weight records in pounds from the same table rows.
  if (record.lb) return record.lb;
  const unit = record.unit === "tons" ? "lb" : "lb/acre";
  const value = Math.round(record.value * LB_PER_TON);
  return {
    ...record,
    unit,
    value,
    decimals: 0,
    rounding: `${record.rounding ?? ""} Pounds to the nearest lb.`.trim(),
    steps: [
      ...record.steps,
      {
        text: `${plain(record.value, 4)} ${record.unit} x 2,000 lb/ton = ${plain(value, 0)} ${unit}`,
        expr: `${record.value}*2000`,
        result: value,
        round: 0,
      },
    ],
    inputs: [
      ...record.inputs,
      {
        name: "Pounds per ton",
        value: LB_PER_TON,
        unit: "lb/ton",
        source: "US short ton: 2,000 lb",
        source_url: null,
        links: [],
        derived_from: [],
        source_verified: true,
        kind: "constant",
        is_estimate: false,
        estimate_reason: null,
        not_estimate_reason: "Unit conversion",
      },
    ],
  };
}

/** True when the number depends on any estimated input. */
export const isEstimated = (record) =>
  Boolean(record?.is_estimate ?? record?.inputs?.some((i) => i.is_estimate));

const fmtDelta = (v, unit, d) => {
  if (unit === "$") return signedMoney(v);
  if (unit === "%") return `${plain(v, d)} pp`;
  return `${plain(v, d)} ${unit}`;
};

/** Source of one side of a comparison: the data behind that side's own box. */
function comparedSource(who, record) {
  const inputs = record.inputs ?? [];
  const estimated = inputs.filter((i) => i.is_estimate);
  const links = unique(
    inputs.flatMap((i) => sourceParts(i).links),
    (l) => l.url,
  );
  return {
    source: `${who} results, shown in the "${record.label}" box. The data behind it is listed there.`,
    source_url: links[0]?.url ?? null,
    links,
    derived_from: unique(estimated.flatMap((i) => i.derived_from ?? [])),
    source_verified: inputs.every((i) => i.source_verified !== false),
  };
}

/**
 * Changed minus original, built from the two backend records so the popover
 * shows the same rounded numbers as the comparison table.
 */
export function differenceRecord(changed, original, label) {
  if (!changed || !original || !finite(changed.value) || !finite(original.value)) return null;
  const d = Math.max(changed.decimals ?? 0, original.decimals ?? 0);
  const value = Number((changed.value - original.value).toFixed(d));
  const unit = changed.unit;
  const show = (r) => formatRecordValue(r);
  return {
    id: `difference.${changed.id}`,
    label,
    value,
    unit: unit === "%" ? "pp" : unit,
    decimals: d,
    formula_text: "Changed scenario value minus original farm value",
    rounding: "Same rounding as the two values it subtracts.",
    is_estimate: isEstimated(changed) || isEstimated(original),
    steps: [
      {
        text: `${show(changed)} - ${show(original)} = ${fmtDelta(value, unit, d)}`,
        expr: `${changed.value}-${original.value}`,
        result: value,
        round: d,
      },
    ],
    inputs: [
      ["Changed scenario", changed],
      ["Original farm", original],
    ].map(([who, r]) => ({
      name: `${who}: ${r.label}`,
      value: r.value,
      unit: r.unit,
      ...comparedSource(who, r),
      kind: "model",
      is_estimate: isEstimated(r),
      estimate_reason: isEstimated(r) ? "Model estimate from the backtest" : null,
      not_estimate_reason: isEstimated(r) ? null : "Computed from reported inputs only",
    })),
  };
}

export function inputReference(input) {
  const { links } = sourceParts(input);
  const text = input.source ?? "";
  const assumption = /^(default assumption|placeholder|team assumption|team estimate)/i.test(text);
  const years = [...new Set(input.name?.match(/\b(?:19|20)\d{2}\b/g) ?? [])];
  return {links, year: input.source_year ?? input.year ?? (years.length ? years.join(", ") : "—"),
    basis: assumption ? "Assumption" : /farmer input/i.test(text) ? "Farmer input" : input.kind === "constant" ? "Conversion / count" : input.kind === "model" ? "Calculated" : "Reference"};
}

/** Keep the process and result; substituted arithmetic remains in Download. */
export function compactStep(step, index, count) {
  const left = step.text.split(" = ")[0];
  let process = /^Sum of /i.test(left) ? "Sum yearly values" :
    left.includes(":") ? left.split(":")[0] :
    /\/ [\d,.]+ years/i.test(left) ? "Divide by years with data" :
    /lb\/ton|mm per|cents per/i.test(left) ? "Convert units" :
    index === count - 1 ? "Apply formula" : "Calculate intermediate result";
  const result = step.text.includes(", rounded to ") ? step.text.split(", rounded to ").at(-1) : step.text.split(" = ").at(-1);
  return `${process} = ${result}`;
}
export function formulaEquation(record) {
  const label = record.label.split(",")[0].replace(/^Estimated /i, "");
  const seasonal = /\.(?:19|20)\d{2}\./.test(record.id);
  return `${label}${seasonal ? "(year)" : ""} = ${record.formula_text}`;
}
