import {
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { CROPS, number } from "../../domain.js";
import "./summary.css";

const UNIT_NAMES = { LB: "lb", TONS: "tons", TON: "tons", BU: "bushels", CWT: "cwt" };
export const unitName = (u) => (u ? (UNIT_NAMES[u.toUpperCase()] ?? u.toLowerCase()) : null);

/** One small chart per crop entry, each in its own real unit. */
export default function ProductionChart({ result }) {
  const items = result.production ?? [];
  if (!items.length)
    return (
      <div className="empty-inline">
        Production in tons or pounds is not available from this backend.
      </div>
    );
  return (
    <div className="production-grid">
      {items.map((p) => {
        const crop = CROPS[p.crop];
        const unit = unitName(p.unit);
        const hasData = unit && p.yearly.some((y) => y.value != null);
        return (
          <div className="production-card" key={p.block_id}>
            <div className="production-title">
              <span className="crop-dot" style={{ background: crop?.color }} />
              <strong>{crop?.name ?? p.crop}</strong>
              <small>
                {p.block_id} · {unit ?? "no baseline yield"}
              </small>
            </div>
            {hasData ? (
              <div className="production-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={p.yearly} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="#e5e9df" />
                    <XAxis dataKey="year" tick={{ fontSize: 10 }} minTickGap={24} />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      width={52}
                      tickFormatter={(v) =>
                        v >= 10000 ? `${number(v / 1000)}k` : number(v)
                      }
                    />
                    <Tooltip
                      formatter={(v) => [`${number(v, unit === "lb" ? 0 : 1)} ${unit}`, crop?.name]}
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
