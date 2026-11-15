import { useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ReferenceArea,
} from "recharts";
import { CROPS } from "../../domain.js";
import { useYieldUnit, YieldUnitToggle } from "./YieldUnitContext.jsx";
import { formatAxisTick, unitLabel } from "./yieldUnits.js";
import { blockLabel, hasWeight, weightByBlock, weightRow } from "./yieldData.js";
import { detailFor, harvestSentence, lossCause } from "./harvestLoss.js";
import { getChartRows } from "../provenance/chartData.js";
import ChartDataTable from "../summary/ChartDataTable.jsx";
import "./yield.css";

const ALL = "__all__";
const tooltipStyle = {
  border: "1px solid #dce3d6",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 10px 25px #1c3d3010",
};

/**
 * Hover box: one plain sentence per crop in the bar, in real weight units, for
 * example "2021: 0.950 tons/acre. That's 0.050 tons/acre less than a full
 * harvest, lost to heat."
 */
function HarvestTooltip({ active, label: year, result, blockIds, blocks, unit, perAcre }) {
  if (!active || year == null) return null;
  const weights = weightByBlock(result);
  const lines = blockIds.map((id) => {
    const row = weightRow(weights.get(id), year);
    const block = blocks.find((b) => b.id === id);
    return harvestSentence({
      year,
      name: blockIds.length > 1 ? blockLabel(block, blocks) : null,
      tons: perAcre ? row?.tons_per_acre : row?.tons,
      relativeYield: row?.relative_yield,
      unit,
      perAcre,
      cause: lossCause(detailFor(result, id, year)),
    });
  });
  return (
    <div className="harvest-tooltip" style={tooltipStyle}>
      {blockIds.length > 1 && <strong>{year}</strong>}
      {lines.map((text, i) => (
        <p key={blockIds[i]}>{text}</p>
      ))}
    </div>
  );
}

/**
 * Yield tab: harvest weight as bars, one bar per year. Hovering a bar explains
 * the harvest and any loss to heat or water in real units. Reads result.yield_weight.
 */
export default function YieldWeightChart({ result, mock }) {
  const { unit } = useYieldUnit();
  const blocks = result?.blocks ?? [];
  const [selected, setSelected] = useState(blocks[0]?.id ?? ALL);
  const [perAcre, setPerAcre] = useState(true);
  const weights = weightByBlock(result);

  if (!weights.size)
    return (
      <div className="empty-inline yield-empty">
        Harvest weight is not in this response yet. Restart the backend to get
        yield in tons.
      </div>
    );

  const missing = blocks.filter((b) => !hasWeight(weights.get(b.id)));
  const scope = selected === ALL ? "farm" : selected;
  // One array for the bars and the table under them.
  const data = getChartRows(result, { chart: "yield", scope, perAcre, unit });
  const rows = data.rows;
  const years = result.years ?? [];
  const label = unitLabel(unit, perAcre);
  const selectedBlock = blocks.find((b) => b.id === selected);
  const selectedEmpty = selected !== ALL && !hasWeight(weights.get(selected));
  const noneWithWeight = !data.series.length;
  const top = data.series.at(-1)?.key;
  const shownIds = data.series.map((sr) => sr.blockId ?? selected);

  return (
    <div className="yield-weight">
      <div className="yield-controls">
        <div className="yield-chips" role="group" aria-label="Crop to show">
          {blocks.map((b) => (
            <button
              key={b.id}
              type="button"
              className="yield-chip"
              aria-pressed={selected === b.id}
              onClick={() => setSelected(b.id)}
            >
              <span
                className="crop-dot"
                style={{ background: CROPS[b.crop]?.color ?? "#557f65" }}
              />
              {blockLabel(b, blocks)}
            </button>
          ))}
          {blocks.length > 1 && (
            <button
              type="button"
              className="yield-chip"
              aria-pressed={selected === ALL}
              onClick={() => setSelected(ALL)}
            >
              All crops
            </button>
          )}
        </div>
        <div className="yield-toggles">
          <div className="segmented" role="group" aria-label="Weight basis">
            <button
              type="button"
              aria-pressed={perAcre}
              onClick={() => setPerAcre(true)}
            >
              Per acre
            </button>
            <button
              type="button"
              aria-pressed={!perAcre}
              onClick={() => setPerAcre(false)}
            >
              Total
            </button>
          </div>
          <YieldUnitToggle />
        </div>
      </div>
      <p className="caption">
        {label} · Shaded years are flagged by the backend, not detected by this
        chart.{mock ? " Demo dips are intentionally constructed." : ""}
      </p>
      {selectedEmpty || noneWithWeight ? (
        <div className="empty-inline yield-empty">
          {selectedEmpty
            ? `No baseline yield for ${CROPS[selectedBlock?.crop]?.name ?? selectedBlock?.crop ?? "this crop"} at this location, so its harvest weight is not available.`
            : "No crop has a baseline yield at this location, so harvest weight is not available."}
        </div>
      ) : (
        <div
          className="chart-wrap"
          role="img"
          aria-label={`Harvest weight in ${label} across ${years.length} historical seasons. Exact values are in the year table below.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={rows}
              margin={{ top: 22, right: 15, left: 6, bottom: 0 }}
              barGap={2}
            >
              <CartesianGrid
                strokeDasharray="3 4"
                vertical={false}
                stroke="#e5e9df"
              />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} minTickGap={20} />
              <YAxis
                tickFormatter={(v) => formatAxisTick(v, "tons")}
                tick={{ fontSize: 11 }}
                width={62}
                label={{
                  value: label,
                  angle: -90,
                  position: "insideLeft",
                  offset: 0,
                  style: {
                    fontSize: 11,
                    fill: "#7b8877",
                    textAnchor: "middle",
                  },
                }}
              />
              {rows
                .filter((r) => r.drought)
                .map((r) => (
                  <ReferenceArea
                    key={r.year}
                    x1={r.year}
                    x2={r.year}
                    fill="#d7be85"
                    fillOpacity={0.22}
                    ifOverflow="extendDomain"
                  />
                ))}
              <Tooltip
                cursor={{ fill: "#244d3b0d" }}
                content={
                  <HarvestTooltip
                    result={result}
                    blockIds={shownIds}
                    blocks={blocks}
                    unit={unit}
                    perAcre={perAcre}
                  />
                }
              />
              {data.series.length > 1 && (
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12, paddingTop: 16 }} />
              )}
              {data.series.map((sr) => (
                <Bar
                  key={sr.key}
                  dataKey={sr.key}
                  name={sr.label}
                  stackId="harvest"
                  fill={sr.color}
                  radius={sr.key === top ? [3, 3, 0, 0] : 0}
                  maxBarSize={44}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="caption">
        Bar height is harvest weight. Hover a bar to see how much harvest was
        lost to heat or not enough water that year.
      </p>
      {selected === ALL && missing.length > 0 && (
        <p className="caption">
          Not shown (no baseline yield):{" "}
          {missing.map((b) => blockLabel(b, blocks)).join(", ")}.
        </p>
      )}
      <ChartDataTable
        data={data}
        title={selected === ALL ? "Whole farm (bars stacked by crop)" : blockLabel(selectedBlock, blocks)}
      />
    </div>
  );
}
