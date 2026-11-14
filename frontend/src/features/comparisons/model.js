import { IRRIGATION, MONTHS, clone } from "../../domain.js";

export function comparisonGroups(farm, comparisons) {
  if (!Array.isArray(comparisons)) return [];
  return farm.blocks
    .map((block) => ({
      block,
      rows: comparisons.filter((row) => row.block_id === block.id),
    }))
    .filter((group) => group.rows.length);
}
export function alternativeLabel(row) {
  if (row.kind === "planting_window") {
    const window = (value) =>
      `${MONTHS[value.start_month - 1]} to ${MONTHS[value.end_month - 1]}`;
    return `Planting ${window(row.alternative)} instead of ${window(row.current)}`;
  }
  return `${IRRIGATION[row.alternative.irrigation] ?? row.alternative.irrigation} instead of ${(IRRIGATION[row.current.irrigation] ?? row.current.irrigation).toLowerCase()}`;
}
export function difference(value, kind) {
  if (value == null || !Number.isFinite(value))
    return { text: "No price data", tone: "unavailable" };
  const rounded =
    Math.round(value * (kind === "money" ? 1 : kind === "yield" ? 100 : 10)) /
    (kind === "money" ? 1 : kind === "yield" ? 100 : 10);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  const amount = Math.abs(rounded).toLocaleString("en-US", {
    maximumFractionDigits: kind === "yield" ? 2 : kind === "water" ? 1 : 0,
  });
  const suffix = kind === "yield" ? " pts" : kind === "water" ? " acre-ft" : "";
  const favorable = kind === "water" ? rounded < 0 : rounded > 0;
  return {
    text: `${sign}${kind === "money" ? "$" : ""}${amount}${suffix}`,
    tone: rounded === 0 ? "neutral" : favorable ? "positive" : "negative",
  };
}
export function comparisonChange(farm, row) {
  const block = farm.blocks.find((block) => block.id === row.block_id);
  if (!block) return null;
  return { ...clone(block), ...clone(row.alternative) };
}
