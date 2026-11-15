import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Info, X } from "lucide-react";
import { CROPS, money } from "../../domain.js";
import { useYieldUnit } from "../yield/YieldUnitContext.jsx";
import { METRIC_TITLES, simpleExplanation, financialScope } from "./simpleExplanation.js";
import "./provenance.css";
const Context = createContext(null);
export function MetricInfo({ metric = "summary", blockId, year, label }) {
  const open = useContext(Context);
  return open ? (
    <button
      type="button"
      className="metric-info"
      aria-label={`How calculated: ${label ?? METRIC_TITLES[metric] ?? metric}${year ? `, ${year}` : ""}${blockId ? `, ${blockId}` : ""}`}
      onClick={() => open({ metric, blockId, year })}
    >
      <Info size={15} aria-hidden="true" />
    </button>
  ) : null;
}
function CalculationPanel({ target, result, close }) {
  const dialog = useRef(null),
    previous = useRef(null);
  const { unit } = useYieldUnit();
  const [crop, setCrop] = useState(target.blockId ?? result.blocks[0]?.id);
  const selected =
    target.metric === "full_yield" ? { ...target, blockId: crop } : target;
  const explanation = simpleExplanation(result, selected, unit);
  useEffect(() => {
    previous.current = document.activeElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous.current?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="calculation-dialog simple-calculation"
      onCancel={close}
      aria-labelledby="calculation-title"
    >
      <div className="calculation-header">
        <h2 id="calculation-title">{explanation.title}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close calculation"
        >
          <X size={20} />
        </button>
      </div>
      <p className="caption">{explanation.scope}</p>
      {target.metric === "full_yield" && (
        <label className="simple-crop-label">
          Crop reference
          <select value={crop} onChange={(e) => setCrop(e.target.value)}>
            {result.blocks.map((b) => (
              <option key={b.id} value={b.id}>
                {CROPS[b.crop]?.name ?? b.crop} · {b.id}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="equation">{explanation.formula}</p>
      <dl className="simple-origins">
        {explanation.origins.map((item, index) => (
          <div key={index}>
            <dt>{item.label}</dt>
            <dd>{item.text}</dd>
          </div>
        ))}
      </dl>
      {explanation.note && <p className="caption">{explanation.note}</p>}
      {explanation.links.length > 0 && (
        <details className="simple-sources">
          <summary>Source links</summary>
          <ul>
            {explanation.links.map((link) => (
              <li key={link.url}>
                <a href={link.url} target="_blank" rel="noreferrer">
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="caption">
        Figures are rounded for reading. Full precision and source inputs remain
        in Download.
      </p>
    </dialog>
  );
}
export function CalculationProvider({ result, children }) {
  const [target, setTarget] = useState(null);
  return (
    <Context.Provider value={setTarget}>
      {children}
      {target && (
        <CalculationPanel
          key={JSON.stringify(target)}
          target={target}
          result={result}
          close={() => setTarget(null)}
        />
      )}
    </Context.Provider>
  );
}
export function MoneyExplanation({ result }) {
  const d = result.calculation_details;
  if (!d) return null;
  const scope = financialScope(result);
  return (
    <div className="money-explanation" role="note">
      <strong>
        Known sales {money(d.reconciliation.avg_revenue)}<MetricInfo metric="avg_revenue" />
        {" · "}Known operating cost {money(d.reconciliation.avg_cost)}<MetricInfo metric="avg_cost" />
        {" · "}{scope.complete ? "Operating margin" : `Margin for ${scope.count} of ${scope.total_blocks} crops`}{" "}
        {money(d.reconciliation.avg_profit)} per year<MetricInfo metric="avg_profit" />
      </strong>
      {!scope.complete && <p>Whole-farm margin unavailable. Sales include crops whose costs may be missing; the margin includes only crops with both sales and costs.</p>}
      <p>
        Costs use regional study references, not your actual expenses. Overhead
        and establishment are excluded.{" "}
        {d.excluded_financial_blocks.length
          ? `${d.excluded_financial_blocks.map((b) => CROPS[b.crop]?.name ?? b.crop).join(", ")} excluded from margin because financial inputs are missing.`
          : ""}
      </p>
    </div>
  );
}
