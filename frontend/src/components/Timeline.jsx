import { CalendarDays } from "lucide-react";
import { MONTHS, CROPS, activeMonth, number } from "../domain.js";
export default function Timeline({ blocks, compact = false }) {
  return (
    <section
      className={`panel timeline-panel ${compact ? "compact" : ""}`}
      aria-label="Crop growing calendar"
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">YOUR YEAR AT A GLANCE</span>
          <h3>
            <CalendarDays size={17} /> Crop calendar
          </h3>
        </div>
        <span className="caption">Updates with your growing months</span>
      </div>
      <div className="timeline-scroll">
        <div className="timeline">
          <div className="timeline-header">
            <span>Crop / area</span>
            {MONTHS.map((m) => (
              <span key={m}>{m}</span>
            ))}
          </div>
          {blocks.map((b) => (
            <div className="timeline-row" key={b.id}>
              <div className="timeline-name">
                <i style={{ background: CROPS[b.crop]?.color }} />
                <span>
                  {CROPS[b.crop]?.name ?? b.crop}
                  <small>
                    {number(b.acres, 1)} acres · {b.id}
                  </small>
                </span>
              </div>
              {MONTHS.map((m, i) => {
                const on = activeMonth(
                  i + 1,
                  Number(b.start_month),
                  Number(b.end_month),
                );
                return (
                  <span
                    key={m}
                    className={`month-cell ${on ? "active" : ""}`}
                    style={
                      on ? { "--crop-color": CROPS[b.crop]?.color } : undefined
                    }
                    aria-label={`${m}: ${on ? "growing" : "not growing"}`}
                  >
                    {on && <span />}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="caption">
        Each row is a crop entry, not necessarily a separate field. November to
        April wraps across the new year.
      </p>
    </section>
  );
}
