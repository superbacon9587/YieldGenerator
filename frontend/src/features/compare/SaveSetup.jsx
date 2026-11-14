import { useState } from "react";
import { Bookmark, Check } from "lucide-react";
import { addSetup, loadSetups, persistSetups } from "./savedSetups.js";
import { summaryOf } from "../summary/landBudget.js";
import "./compare.css";

/** "Save this setup": asks for a name, stores {name, farm, saved_at, summary_stats}. */
export default function SaveSetup({ farm, result }) {
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [status, setStatus] = useState("");
  function save(e) {
    e.preventDefault();
    const clean = name.trim();
    if (!clean) {
      setStatus("Enter a name for this setup.");
      return;
    }
    const existing = loadSetups();
    const replaced = existing.some((s) => s.name === clean);
    const ok = persistSetups(
      addSetup(existing, { name: clean, farm, summary_stats: summaryOf(result) }),
    );
    setStatus(
      ok
        ? `${replaced ? "Updated" : "Saved"} "${clean}". Open Compare setups to see it.`
        : "This browser could not save setups.",
    );
    if (ok) {
      setOpen(false);
      setName("");
    }
  }
  return (
    <div className="save-setup">
      {open ? (
        <form onSubmit={save} className="save-setup-form">
          <input
            aria-label="Setup name"
            placeholder="Name this setup"
            value={name}
            maxLength={80}
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="secondary">
            <Check size={15} /> Save
          </button>
          <button type="button" className="text-button" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <button
          className="secondary"
          onClick={() => {
            setOpen(true);
            setStatus("");
          }}
        >
          <Bookmark size={15} /> Save this setup
        </button>
      )}
      {status && (
        <span className="save-setup-status" role="status">
          {status}
        </span>
      )}
    </div>
  );
}
