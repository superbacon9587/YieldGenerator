import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info, Printer, X } from "lucide-react";
import { useYieldUnit } from "../yield/YieldUnitContext.jsx";
import {
  formatRecordValue,
  inWeightUnit,
  isEstimated,
} from "./calcRecords.js";
import "./provenance.css";

// The calculation records of the response shown on this part of the page.
const Records = createContext({});

export function CalcRecords({ records, children }) {
  return (
    <Records.Provider value={records ?? {}}>{children}</Records.Provider>
  );
}

const inputValue = (v) =>
  typeof v === "number"
    ? v.toLocaleString("en-US", { maximumFractionDigits: 6 })
    : String(v ?? "Not available");

function Popover({ record, display, close }) {
  const dialog = useRef(null);
  const previous = useRef(null);
  useEffect(() => {
    previous.current = document.activeElement;
    dialog.current?.showModal?.();
    return () => {
      dialog.current?.close?.();
      previous.current?.focus?.();
    };
  }, []);
  const estimated = isEstimated(record);
  return (
    <dialog
      ref={dialog}
      className="calc-popover"
      onCancel={close}
      onClick={(e) => e.target === dialog.current && close()}
      aria-labelledby="calc-title"
    >
      <header className="calc-head">
        <h2 id="calc-title">
          {record.label}: <b>{display ?? formatRecordValue(record)}</b>
          {estimated && <span className="calc-tag">Estimated value</span>}
        </h2>
        <div className="calc-actions">
          <button
            type="button"
            className="icon-button"
            onClick={() => window.print()}
            aria-label="Print this calculation"
          >
            <Printer size={16} />
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={close}
            aria-label="Close calculation"
          >
            <X size={18} />
          </button>
        </div>
      </header>
      <p className="calc-formula">{record.formula_text}</p>
      <ol className="calc-steps">
        {record.steps.map((s, i) => (
          <li key={i}>{s.text}</li>
        ))}
      </ol>
      <table className="calc-inputs">
        <thead>
          <tr>
            <th>Input</th>
            <th>Value</th>
            <th>Unit</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {record.inputs.map((i, n) => (
            <tr key={n} className={i.is_estimate ? "calc-estimate" : ""}>
              <th scope="row">
                {i.name}
                {i.is_estimate && (
                  <>
                    <span className="calc-tag">Estimate</span>
                    <small>{i.estimate_reason}</small>
                  </>
                )}
              </th>
              <td>{inputValue(i.value)}</td>
              <td>{i.unit}</td>
              <td>
                {i.source_url ? (
                  <a href={i.source_url} target="_blank" rel="noreferrer">
                    {i.source}
                  </a>
                ) : (
                  i.source
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {record.rounding && <p className="calc-rounding">{record.rounding}</p>}
    </dialog>
  );
}

/**
 * Information button for one number. Pass the record id (looked up in the
 * nearest CalcRecords) or a record. Renders nothing when there is no record.
 * `display` is the text printed next to the button, repeated at the top.
 */
export function CalcInfo({ id, record, display, weightUnit, label }) {
  const records = useContext(Records);
  const { unit } = useYieldUnit();
  const [open, setOpen] = useState(false);
  const found = record ?? records[id];
  if (!found) return null;
  const shown = inWeightUnit(found, weightUnit ?? unit);
  return (
    <>
      <button
        type="button"
        className="metric-info"
        aria-label={`How calculated: ${label ?? shown.label}`}
        onClick={() => setOpen(true)}
      >
        <Info size={14} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <Popover
            record={shown}
            display={display}
            close={() => setOpen(false)}
          />,
          document.body,
        )}
    </>
  );
}
