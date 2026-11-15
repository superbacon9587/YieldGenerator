import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info, Printer, X } from "lucide-react";
import { useYieldUnit } from "../yield/YieldUnitContext.jsx";
import {
  formatRecordValue,
  inWeightUnit,
  isEstimated,
  sourceParts,
  inputReference,
  compactStep,
  formulaEquation,
  tableEquations,
} from "./calcRecords.js";
import "./provenance.css";

// The calculation records of the response shown on this part of the page.
const Records = createContext({});

export function CalcRecords({ records, children }) {
  return (
    <Records.Provider value={records ?? {}}>{children}</Records.Provider>
  );
}

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
      <details className="calc-working" open><summary>Calculation steps</summary>
        <ol className="calc-steps">{record.steps.map((step,index) => <li key={index}>{compactStep(step,index,record.steps.length)}</li>)}</ol>
      </details>
      <p className="calc-rounding"><strong>Data sources:</strong> The table uses the original source references (NASA POWER weather, USDA/EIA records and UC Davis studies), plus farmer inputs and model assumptions. Reference links are grouped below.</p>
      <div className="calc-formulas" aria-label="Equations">
        {tableEquations(record).map(equation => <p className="calc-formula" key={equation}>{equation}</p>)}
        <p className="calc-formula">{formulaEquation(record)}</p>
      </div>
      <div className="calc-table-scroll"><table className="calc-inputs">
        <thead><tr><th>Input</th><th>Value</th><th>Year</th></tr></thead>
        <tbody>{record.inputs.map((input,index) => <tr key={index}>
          <th scope="row">{input.name}{inputReference(input).basis === "Assumption" && <small>Assumption</small>}</th>
          <td>{typeof input.value === "number" ? input.value.toLocaleString("en-US",{maximumFractionDigits:6}) : String(input.value ?? "Not available")} {input.unit}</td>
          <td>{inputReference(input).year}</td>
        </tr>)}</tbody>
      </table></div>
      <details className="calc-working">
        <summary>Reference links</summary>
        <span className="calc-links">
          {[...new Map(record.inputs.flatMap(i => sourceParts(i).links).map(l => [l.url,l])).values()].map(l =>
            <a key={l.url} href={l.url} target="_blank" rel="noreferrer">{l.label}</a>)}
        </span>
      </details>
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
