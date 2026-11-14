import { useState } from "react";
import { LandPlot } from "lucide-react";
import { toAcres } from "../../domain.js";
import "./summary.css";

/** "Your land and budget": available acreage (acres or sq ft) and a yearly budget. */
export default function LandBudgetPanel({ farm, setFarm, eyebrow }) {
  const [unit, setUnit] = useState("acres");
  const acres = farm.available_acres;
  const shown =
    acres === "" || acres == null
      ? ""
      : unit === "sqft"
        ? Number(acres) * 43560
        : acres;
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>Your land and budget</h2>
        </div>
        <LandPlot size={21} className="muted-icon" />
      </div>
      <p className="subtle">
        Total land you farm, and what you can spend to run it each year. The
        budget is optional here.
      </p>
      <div className="form-grid two">
        <label>
          Available acreage
          <div className="area-input">
            <input
              aria-label="Available acreage"
              type="number"
              min="0.0001"
              step="any"
              required
              value={shown}
              onChange={(e) =>
                setFarm({
                  ...farm,
                  available_acres:
                    e.target.value === "" ? "" : toAcres(e.target.value, unit),
                })
              }
            />
            <select
              aria-label="Available acreage unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
            >
              <option value="acres">acres</option>
              <option value="sqft">sq ft</option>
            </select>
          </div>
        </label>
        <label>
          Yearly operating budget ($)
          <input
            aria-label="Yearly operating budget"
            type="number"
            min="0"
            step="any"
            placeholder="Optional"
            value={farm.optional.budget_usd ?? ""}
            onChange={(e) =>
              setFarm({
                ...farm,
                optional: { ...farm.optional, budget_usd: e.target.value },
              })
            }
          />
        </label>
      </div>
    </section>
  );
}
