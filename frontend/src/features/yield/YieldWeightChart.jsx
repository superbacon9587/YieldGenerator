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
  LabelList,
} from "recharts";
import { CROPS } from "../../domain.js";
import { useYieldUnit, YieldUnitToggle } from "./YieldUnitContext.jsx";
import {
  formatAxisTick,
  potentialPercent,
  unitLabel,
  weightWithPotential,
} from "./yieldUnits.js";
import {
  blockColor,
  blockLabel,
  chartRows,
  hasWeight,
  labelsFit,
  weightByBlock,
} from "./yieldData.js";
import "./yield.css";

const ALL = "__all__";
const tooltipStyle = {
  border: "1px solid #dce3d6",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 10px 25px #1c3d3010",
};

/**
 * Yield tab: harvest weight as bars, one bar per year, with the year's percent
 * of full potential printed on top. Reads result.yield_weight.
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

  const withWeight = blocks.filter((b) => hasWeight(weights.get(b.id)));
  const missing = blocks.filter((b) => !hasWeight(weights.get(b.id)));
  const shown =
    selected === ALL ? withWeight : blocks.filter((b) => b.id === selected);
  const ids = shown.map((b) => b.id);
  const rows = chartRows(result, ids, perAcre);
  const years = result.years ?? [];
  const showLabels =
    selected !== ALL || labelsFit(years.length, Math.max(1, ids.length));
  const drought = (result.summary?.drought_years ?? []).filter((y) =>
    years.includes(y),
  );
  const label = unitLabel(unit, perAcre);
  const selectedBlock = blocks.find((b) => b.id === selected);
  const selectedEmpty = selected !== ALL && !hasWeight(weights.get(selected));

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
      {selectedEmpty || !ids.length ? (
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
                tickFormatter={(v) => formatAxisTick(v, unit)}
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
              {drought.map((y) => (
                <ReferenceArea
                  key={y}
                  x1={y}
                  x2={y}
                  fill="#d7be85"
                  fillOpacity={0.22}
                  ifOverflow="extendDomain"
                />
              ))}
              <Tooltip
                cursor={{ fill: "#244d3b0d" }}
                contentStyle={tooltipStyle}
                separator=": "
                formatter={(value, name, item) => [
                  weightWithPotential(
                    value,
                    item?.payload?.[`${item.dataKey}__ry`],
                    unit,
                    perAcre,
                  ),
                  name,
                ]}
              />
              {ids.length > 1 && (
                <Legend
                  iconType="circle"
                  wrapperStyle={{ fontSize: 12, paddingTop: 16 }}
                />
              )}
              {shown.map((b) => {
                const { fill, opacity } = blockColor(b, blocks);
                return (
                  <Bar
                    key={b.id}
                    dataKey={b.id}
                    name={blockLabel(b, blocks)}
                    fill={fill}
                    fillOpacity={opacity}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={44}
                    isAnimationActive={false}
                  >
                    {showLabels && (
                      <LabelList
                        dataKey={`${b.id}__ry`}
                        position="top"
                        offset={5}
                        formatter={(v) => potentialPercent(v) ?? ""}
                        style={{
                          fontSize: 9,
                          fontWeight: 700,
                          fill: "#344f35",
                        }}
                      />
                    )}
                  </Bar>
                );
              })}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="caption">
        Bar height is harvest weight. The percent on top is how close the crop
        came to its full potential that year.
        {!showLabels && " Hover a bar to see its percent."}
      </p>
      {selected === ALL && missing.length > 0 && (
        <p className="caption">
          Not shown (no baseline yield):{" "}
          {missing.map((b) => blockLabel(b, blocks)).join(", ")}.
        </p>
      )}
    </div>
  );
}
