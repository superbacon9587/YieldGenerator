// Harvest lost to heat or not enough water, in real weight units instead of a
// percent. Pure functions, no React.
//
// The backend scales harvest as baseline x relative_yield / typical, so a full
// (unstressed) harvest is tons / relative_yield and the amount lost that year is
// tons x (1 / relative_yield - 1). The cause comes from the year's calculation
// details: FAO-33 water loss Ky x (1 - ETa / ETc), and the heat penalty.
import { formatWeight, formatWeightNumber, unitLabel } from "./yieldUnits.js";
import { weightByBlock, weightRow } from "./yieldData.js";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
// Losses smaller than this share of a full harvest are treated as none.
const TINY = 0.001;

/** Tons lost below a full harvest, or null when it cannot be worked out. */
export function lostTons(tons, relativeYield) {
  if (!finite(tons) || !finite(relativeYield) || relativeYield <= 0) return null;
  return Math.max(0, tons * (1 / relativeYield - 1));
}

/** The calculation_details row for one crop entry and year, or null. */
export function detailFor(result, blockId, year) {
  const block = result?.calculation_details?.blocks?.find((b) => b.id === blockId);
  return block?.yearly?.find((r) => r.year === year) ?? null;
}

/**
 * "heat", "water", "both", "none", or "unknown" (no calculation details).
 * Water loss is FAO-33: Ky x (1 - ETa / ETc). Heat is the backend's heat penalty.
 */
export function lossCause(detail) {
  if (!detail) return "unknown";
  const { ky, etc_active_mm: etc, eta_active_mm: eta, heat_penalty_fraction: heat } = detail;
  const water = finite(ky) && finite(etc) && finite(eta) && etc > 0
    ? Math.max(0, ky * (1 - eta / etc))
    : 0;
  const hot = finite(heat) ? heat : 0;
  if (water > TINY && hot > TINY) return "both";
  if (water > TINY) return "water";
  if (hot > TINY) return "heat";
  return "none";
}

const CAUSE_TEXT = {
  heat: "lost to heat",
  water: "lost to not enough water",
  both: "lost to heat and not enough water",
  unknown: "lost to heat or not enough water",
  none: "lost to heat or not enough water",
};

/**
 * Plain sentence for a bar, for example
 * "2021: 0.950 tons/acre. That's 0.050 tons/acre less than a full harvest, lost to heat."
 * name is optional (used when several crops share a bar).
 */
export function harvestSentence({ year, name, tons, relativeYield, unit, perAcre, cause }) {
  const who = name ? `${name}: ` : `${year}: `;
  if (!finite(tons)) return `${who}no harvest estimate.`;
  const harvest = formatWeight(tons, unit, perAcre);
  const lost = lostTons(tons, relativeYield);
  const shown = formatWeightNumber(lost, unit, perAcre);
  if (lost == null) return `${who}${harvest}.`;
  if (lost / (tons + lost) <= TINY || Number(shown.replace(/,/g, "")) === 0)
    return `${who}${harvest}, a full harvest.`;
  return `${who}${harvest}. That's ${shown} ${unitLabel(unit, perAcre)} less than a full harvest, ${CAUSE_TEXT[cause] ?? CAUSE_TEXT.unknown}.`;
}

/**
 * Average harvest lost per acre per year across the whole farm, in tons/acre.
 * Each year adds up the tons lost on every crop entry with a harvest weight and
 * divides by those entries' acres; the result is the mean over years.
 */
export function averageLostPerAcre(result) {
  const weights = weightByBlock(result);
  const blocks = (result?.blocks ?? []).filter((b) => weights.has(b.id));
  const perYear = [];
  for (const year of result?.years ?? []) {
    let lost = 0;
    let acres = 0;
    for (const b of blocks) {
      const row = weightRow(weights.get(b.id), year);
      const l = lostTons(row?.tons, row?.relative_yield);
      if (l == null) continue;
      lost += l;
      acres += b.acres;
    }
    if (acres > 0) perYear.push(lost / acres);
  }
  return perYear.length ? perYear.reduce((a, b) => a + b, 0) / perYear.length : null;
}

/** Explain the new loss card using the existing calculation-info layout. */
export function harvestLossRecord(result) {
  const value = averageLostPerAcre(result);
  if (!finite(value)) return null;
  const weights = weightByBlock(result);
  const inputs = [];
  for (const year of result?.years ?? []) {
    for (const block of result?.blocks ?? []) {
      const row = weightRow(weights.get(block.id), year);
      if (lostTons(row?.tons, row?.relative_yield) == null) continue;
      const source = { source: "Modeled harvest from USDA NASS baseline yields and NASA POWER weather", source_year: year,
        links: [{ label: "USDA NASS Quick Stats", url: "https://quickstats.nass.usda.gov/" },
          { label: "NASA POWER", url: "https://power.larc.nasa.gov/" }] };
      inputs.push(
        { ...source, name: `${block.crop} · ${block.id} harvest`, value: row.tons, unit: "tons" },
        { ...source, name: `${block.crop} · ${block.id} relative yield`, value: row.relative_yield, unit: "fraction" },
        { name: `${block.crop} · ${block.id} acres`, value: block.acres, unit: "acres", source: "Farmer input", source_year: year },
      );
    }
  }
  return { id: "summary.avg_harvest_loss", label: "Average modeled harvest lost per acre", value,
    unit: "tons/acre", decimals: 3, is_estimate: true,
    formula_text: "mean over years of [sum of crop losses ÷ supported crop acres]; crop loss = max(0, harvest × (1 ÷ relative yield − 1))",
    steps: [{ text: `Average yearly modeled loss per supported acre: apply formula = ${value.toFixed(3)} tons/acre`, result: value, expr: String(value) }], inputs };
}
