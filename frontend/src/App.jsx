import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Sprout,
  LayoutDashboard,
  SlidersHorizontal,
  ArrowUpRight,
  FlaskConical,
  PanelLeftClose,
  Scale,
  Target,
  Check,
  Info,
  Menu,
  X,
} from "lucide-react";
import FarmForm from "./components/FarmForm.jsx";
const Results = lazy(() => import("./components/Results.jsx"));
const ComparePage = lazy(() => import("./features/compare/ComparePage.jsx"));
const OptimizePage = lazy(() => import("./features/optimize/OptimizePage.jsx"));
import {
  DEFAULT_FARM,
  clone,
  toSimulateRequest,
  validateFarm,
} from "./domain.js";
import { simulate, USE_MOCK, meta as fetchMeta } from "./api.js";
import {
  FALLBACK_META,
  presetYears,
  withPartADefaults,
} from "./features/summary/landBudget.js";

const STORAGE = "yieldgenerator-farm-v1";
function initialFarm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) || "null");
    if (
      saved?.location &&
      Array.isArray(saved.blocks) &&
      saved.blocks.every(
        (b) =>
          b.id &&
          b.crop in
            {
              almonds: 1,
              walnuts: 1,
              processing_tomatoes: 1,
              corn: 1,
              oats: 1,
              alfalfa_hay: 1,
            },
      ) &&
      Array.isArray(saved.years) &&
      saved.optional
    )
      return withPartADefaults(saved);
  } catch {}
  return clone(DEFAULT_FARM);
}
export default function App() {
  const [farm, setFarm] = useState(initialFarm),
    [view, setView] = useState("farm"),
    [mock, setMock] = useState(USE_MOCK),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState(null),
    [submitted, setSubmitted] = useState(null),
    [navOpen, setNavOpen] = useState(false),
    [saved, setSaved] = useState(true),
    [meta, setMeta] = useState(FALLBACK_META);
  const heading = useRef(null);
  useEffect(() => {
    let live = true;
    fetchMeta({ mock }).then((m) => live && setMeta(m));
    return () => {
      live = false;
    };
  }, [mock]);
  useEffect(() => {
    // Keep preset periods ending at the last full year of weather data.
    if (!farm.period || farm.period === "custom") return;
    const [a, b] = presetYears(farm.period, meta);
    if (Number(farm.years[0]) !== a || Number(farm.years[1]) !== b)
      setFarm((f) => ({ ...f, years: [a, b] }));
  }, [meta, farm.period, farm.years[0], farm.years[1]]);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(farm));
      setSaved(true);
    } catch {
      setSaved(false);
    }
  }, [farm]);
  useEffect(() => {
    heading.current?.focus();
  }, [view]);
  async function run(source = farm) {
    const request = toSimulateRequest(source, meta);
    const errors = validateFarm(request, meta);
    if (errors.length) {
      setError(errors.join(" "));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await simulate(request, { mock });
      setResult(response);
      setSubmitted(request);
      setView("results");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function modeChange(value) {
    setMock(value);
    setResult(null);
    setSubmitted(null);
    setView("farm");
    setError("");
  }
  function navigate(next) {
    setView(next);
    setNavOpen(false);
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("farm");
          }}
        >
          <span className="brand-icon">
            <Sprout size={24} />
          </span>
          <span>
            Yield<span className="brand-light">Generator</span>
            <small>EARTH DATA. FARM DECISIONS.</small>
          </span>
        </a>
        <div className="sidebar-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          <button
            className={view === "farm" ? "active" : ""}
            aria-current={view === "farm" ? "page" : undefined}
            onClick={() => navigate("farm")}
          >
            <SlidersHorizontal size={18} /> Your farm<span>01</span>
          </button>
          <button
            className={view === "results" ? "active" : ""}
            disabled={!result}
            aria-current={view === "results" ? "page" : undefined}
            onClick={() => navigate("results")}
          >
            <LayoutDashboard size={18} /> Backtest results<span>02</span>
          </button>
          <button
            className={view === "compare" ? "active" : ""}
            aria-current={view === "compare" ? "page" : undefined}
            onClick={() => navigate("compare")}
          >
            <Scale size={18} /> Compare setups<span>03</span>
          </button>
          <button
            className={view === "optimize" ? "active" : ""}
            aria-current={view === "optimize" ? "page" : undefined}
            onClick={() => navigate("optimize")}
          >
            <Target size={18} /> Optimize<span>04</span>
          </button>
        </nav>
        <div className="sidebar-note">
          <div className="orbit" aria-hidden="true">
            ✳
          </div>
          <h3>
            Rooted in data.
            <br />
            Made for possibility.
          </h3>
          <p>
            Explore the relationship between crops, water, and changing
            conditions.
          </p>
          <span>NASA SPACE APPS / 2026</span>
        </div>
        <div className="sidebar-bottom">
          <span className="avatar">YG</span>
          <div>
            <strong>Farm workspace</strong>
            <small>Saved on this device</small>
          </div>
          <PanelLeftClose size={17} />
        </div>
      </aside>
      {navOpen && (
        <button
          className="nav-overlay"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="mobile-menu icon-button"
              aria-label="Toggle navigation"
              onClick={() => setNavOpen(!navOpen)}
            >
              {navOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span>{" "}
              <b>
                {view === "farm"
                  ? "Your farm"
                  : view === "optimize"
                    ? "Optimize"
                    : view === "compare"
                    ? "Compare setups"
                    : "Backtest results"}
              </b>
            </span>
          </div>
          <div className="topbar-actions">
            <span className="save-status">
              <Check size={13} />
              {saved ? "Inputs saved" : "Storage unavailable"}
            </span>
            <label className="mode-selector">
              <span className={`status-dot ${mock ? "demo" : "live"}`} />
              <select
                aria-label="Data mode"
                value={mock ? "demo" : "live"}
                disabled={busy}
                onChange={(e) => modeChange(e.target.value === "demo")}
              >
                <option value="demo">Demo mode</option>
                <option value="live">Live backend</option>
              </select>
            </label>
          </div>
        </header>
        <main id="main">
          <div className="page-title">
            <div>
              <p className="eyebrow">
                {view === "farm"
                  ? "START WITH WHAT YOU GROW"
                  : view === "optimize"
                    ? "SAME LAND. SAME WEATHER. MORE OPTIONS."
                    : view === "compare"
                    ? "SAME WEATHER. DIFFERENT SETUPS."
                    : "UNDERSTAND THE PAST. EXPLORE WHAT’S NEXT."}
              </p>
              <h1 ref={heading} tabIndex="-1">
                {view === "farm"
                  ? "Every farm has a story."
                  : view === "optimize"
                    ? "Find a plan."
                    : view === "compare"
                    ? "Compare setups."
                    : "Your farm, through the years."}
              </h1>
              <p>
                {view === "farm"
                  ? "Tell us about yours. Explore yield, water needs, and the possibilities in between."
                  : view === "optimize"
                    ? "Search crop, irrigation, and planting month choices within your land, budget, and water, over the same historical weather."
                    : view === "compare"
                    ? "Put saved setups side by side over the same years and weather."
                    : "Explore historical outcomes, understand the assumptions, and compare a change."}
              </p>
            </div>
            <span className="edition">
              FIELD NOTES
              <br />
              <b>01 / {new Date().getFullYear()}</b>
            </span>
          </div>
          <div className={`mode-banner ${mock ? "demo" : "live"}`} role="note">
            {mock ? <FlaskConical size={20} /> : <Info size={20} />}
            <div>
              <strong>
                {mock
                  ? "Demo workspace. Sample results, not farm predictions."
                  : result
                    ? `${result.location.county || "County not supplied"} / ${result.location.cost_region || "Cost region not supplied"}`
                    : "Live workspace. Ready to run your farm backtest."}
              </strong>
              <span>
                {mock
                  ? "Numbers and drought patterns are synthetic. Use this mode to test the experience while the model is connected."
                  : "Historical weather plus regional yield, price, and cost references. Estimates, not farm accounts. Open the information buttons beside results for exact inputs."}
              </span>
            </div>
            <span className="banner-tag">
              {mock ? "ILLUSTRATIVE DATA" : "MODEL OUTPUT"}
            </span>
          </div>
          {view === "farm" ? (
            <FarmForm
              key={mock ? "demo" : "backend"}
              farm={farm}
              setFarm={setFarm}
              onRun={run}
              busy={busy}
              error={error}
              mock={mock}
              meta={meta}
              onReset={() => {
                setFarm(clone(DEFAULT_FARM));
                setError("");
              }}
            />
          ) : view === "optimize" ? (
            <Suspense
              fallback={
                <div className="panel" role="status">
                  Loading the optimizer...
                </div>
              }
            >
              <OptimizePage
                farm={farm}
                setFarm={setFarm}
                mock={mock}
                onBacktest={(next) => {
                  setFarm(next);
                  setError("");
                  setView("farm");
                  run(next);
                }}
              />
            </Suspense>
          ) : view === "compare" ? (
            <Suspense
              fallback={
                <div className="panel" role="status">
                  Loading saved setups...
                </div>
              }
            >
              <ComparePage
                mock={mock}
                onLoad={(saved) => {
                  setFarm(withPartADefaults(clone(saved)));
                  setError("");
                  setView("farm");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            </Suspense>
          ) : (
            <Suspense
              fallback={
                <div className="panel" role="status">
                  Loading the results dashboard...
                </div>
              }
            >
              <Results
                key={`${submitted.location.label}-${mock}-${JSON.stringify(submitted)}`}
                farm={submitted}
                result={result}
                mock={mock}
                onBack={() => setView("farm")}
              />
            </Suspense>
          )}
          <footer>
            <span>
              <Sprout size={14} /> YieldGenerator · NASA Space Apps 2026
            </span>
            <span>Better questions before bigger decisions.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
