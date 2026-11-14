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
import { hasWeight } from "../yield/yieldData.js";
import {
  formatAxisTick,
  formatWeight,
  toUnit,
  unitLabel,
} from "../yield/yieldUnits.js";
import "./summary.css";

/** One small chart per crop entry: total harvest weight per year, from yield_weight. */
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
        const rows = (w.yearly ?? []).map((r) => ({
          year: r.year,
          tons: r.tons ?? null,
          value: toUnit(r.tons, unit),
        }));
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
                  <BarChart
                    data={rows}
                    margin={{ top: 6, right: 6, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 4"
                      vertical={false}
                      stroke="#e5e9df"
                    />
                    <XAxis
                      dataKey="year"
                      tick={{ fontSize: 10 }}
                      minTickGap={24}
                    />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      width={52}
                      tickFormatter={(v) =>
                        formatAxisTick(unit === "lb" ? v / 2000 : v, unit)
                      }
                    />
                    <Tooltip
                      formatter={(_, __, item) => [
                        formatWeight(item?.payload?.tons, unit, false),
                        crop?.name,
                      ]}
                      contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    />
                    <Bar
                      dataKey="value"
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
          </div>
        );
      })}
    </div>
  );
}
