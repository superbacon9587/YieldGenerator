// Calculation records from the backend (backend/calculations.py). Pure helpers, no React.
//   record = {id, label, value, unit, decimals, formula_text, is_estimate,
//             steps: [{text, expr, result}],
//             inputs: [{name, value, unit, source, source_url, kind, is_estimate,
//                       estimate_reason, not_estimate_reason}]}
import { LB_PER_TON } from "../yield/yieldUnits.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const WEIGHT_UNITS = new Set(["tons", "tons/acre"]);

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
  const unit = record.unit === "tons" ? "lb" : "lb/acre";
  const value = Math.round(record.value * LB_PER_TON);
  return {
    ...record,
    unit,
    value,
    decimals: 0,
    steps: [
      ...record.steps,
      {
        text: `${plain(record.value, 4)} ${record.unit} x 2,000 lb/ton = ${plain(value, 0)} ${unit}`,
        expr: `${record.value}*2000`,
        result: value,
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
    is_estimate: isEstimated(changed) || isEstimated(original),
    steps: [
      {
        text: `${show(changed)} - ${show(original)} = ${fmtDelta(value, unit, d)}`,
        expr: `${changed.value}-${original.value}`,
        result: value,
      },
    ],
    inputs: [
      ["Changed scenario", changed],
      ["Original farm", original],
    ].map(([who, r]) => ({
      name: `${who}: ${r.label}`,
      value: r.value,
      unit: r.unit,
      source: `${who} backtest, ${r.id}`,
      source_url: null,
      kind: "model",
      is_estimate: isEstimated(r),
      estimate_reason: isEstimated(r) ? "Model estimate from the backtest" : null,
      not_estimate_reason: isEstimated(r) ? null : "Computed from reported inputs only",
    })),
  };
}
