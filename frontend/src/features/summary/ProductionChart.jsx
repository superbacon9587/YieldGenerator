import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { CROPS } from "../../domain.js";
import { useYieldUnit } from "../yield/YieldUnitContext.jsx";
import { blockLabel, hasWeight } from "../yield/yieldData.js";
import { formatAxisTick, unitLabel } from "../yield/yieldUnits.js";
import { formatCell, getChartRows } from "../provenance/chartData.js";
import ChartDataTable from "./ChartDataTable.jsx";
import "./summary.css";

/** One chart per crop entry: total harvest per year, with its table from the same rows. */
export default function ProductionChart({ result }) {
  const { unit } = useYieldUnit();
  const items = Array.isArray(result?.yield_weight) ? result.yield_weight : [];
  if (!items.length)
    return (
      <div className="empty-inline">
        Harvest weight is not available from this backend.
      </div>
    );
  return (
    <div className="production-grid">
      {items.map((w) => {
        const crop = CROPS[w.crop];
        const block = result.blocks.find((b) => b.id === w.block_id) ?? { crop: w.crop, id: w.block_id };
        const data = getChartRows(result, { chart: "production", scope: w.block_id, unit });
        return (
          <div className="production-card" key={w.block_id}>
            <div className="production-title">
              <span className="crop-dot" style={{ background: crop?.color }} />
              <strong>{crop?.name ?? w.crop}</strong>
              <small>
                {w.block_id} ·{" "}
                {hasWeight(w) ? unitLabel(unit, false) : "no baseline yield"}
              </small>
            </div>
            {hasWeight(w) ? (
              <div className="production-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.rows} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="#e5e9df" />
                    <XAxis dataKey="year" tick={{ fontSize: 10 }} minTickGap={24} />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      width={52}
                      tickFormatter={(v) => formatAxisTick(v, "tons")}
                    />
                    <Tooltip
                      formatter={(v) => [`${formatCell("harvest", v, { unit })} ${unitLabel(unit, false)}`, crop?.name]}
                      contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    />
                    <Bar
                      dataKey={data.series[0].key}
                      fill={crop?.color ?? "#557f65"}
                      radius={[2, 2, 0, 0]}
                      isAnimationActive={false}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="empty-inline">
                Not available: no baseline yield for this crop here.
              </div>
            )}
            <ChartDataTable result={result} data={data} title={blockLabel(block, result.blocks)} />
          </div>
        );
      })}
    </div>
  );
}
