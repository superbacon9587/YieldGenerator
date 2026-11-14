import { createContext, useContext, useEffect, useState } from "react";
import { YIELD_UNITS } from "./yieldUnits.js";

// App-wide harvest weight unit ("tons" or "lb"), remembered on this device.
const STORAGE = "yieldgenerator-yield-unit";
const YieldUnitContext = createContext({ unit: "tons", setUnit: () => {} });

function initialUnit() {
  try {
    const saved = localStorage.getItem(STORAGE);
    return saved in YIELD_UNITS ? saved : "tons";
  } catch {
    return "tons";
  }
}

export function YieldUnitProvider({ children }) {
  const [unit, setUnit] = useState(initialUnit);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE, unit);
    } catch {}
  }, [unit]);
  return (
    <YieldUnitContext.Provider value={{ unit, setUnit }}>
      {children}
    </YieldUnitContext.Provider>
  );
}

export const useYieldUnit = () => useContext(YieldUnitContext);

export function YieldUnitToggle() {
  const { unit, setUnit } = useYieldUnit();
  return (
    <div className="segmented" role="group" aria-label="Harvest weight unit">
      {Object.entries(YIELD_UNITS).map(([key, label]) => (
        <button
          key={key}
          type="button"
          aria-pressed={unit === key}
          onClick={() => setUnit(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
