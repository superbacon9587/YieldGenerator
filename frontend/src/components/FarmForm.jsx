import { useState } from "react";
import {
  MapPin,
  Plus,
  Trash2,
  ArrowUpRight,
  RotateCcw,
  SlidersHorizontal,
  Search,
  LoaderCircle,
} from "lucide-react";
import {
  CROPS,
  IRRIGATION,
  MONTHS,
  irrigationIssue,
  irrigationsFor,
  waterSourceKind,
  waterSourceShare,
  number,
  toAcres,
} from "../domain.js";
import { geocode } from "../api.js";
import Timeline from "./Timeline.jsx";
import LandBudgetPanel from "../features/summary/LandBudgetPanel.jsx";
import LandCheck from "../features/summary/LandCheck.jsx";
import PeriodPresets from "../features/summary/PeriodPresets.jsx";

function BlockEditor({ block, index, onChange, onRemove, meta }) {
  const [unit, setUnit] = useState("acres");
  const area = unit === "sqft" ? Number(block.acres) * 43560 : block.acres;
  function update(key, value) {
    onChange({ ...block, [key]: value });
  }
  const priced = irrigationsFor(block.crop, meta);
  const issue = irrigationIssue(block, meta);
  function selectCrop(crop) {
    const ok = irrigationsFor(crop, meta);
    onChange({
      ...block,
      crop,
      irrigation: ok.includes(block.irrigation) ? block.irrigation : (ok[0] ?? block.irrigation),
      ...(CROPS[crop].perennial
        ? { start_month: 1, end_month: 12 }
        : {
            start_month: crop === "oats" ? 11 : 5,
            end_month: crop === "oats" ? 4 : 9,
          }),
    });
  }
  return (
    <div className="crop-editor">
      <div className="crop-id">
        <span style={{ background: CROPS[block.crop].color }}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <small>{block.id}</small>
      </div>
      <label>
        Crop
        <select
          aria-label={`Crop ${index + 1}`}
          value={block.crop}
          onChange={(e) => selectCrop(e.target.value)}
        >
          {Object.entries(CROPS).map(([key, c]) => (
            <option key={key} value={key}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Area
        <div className="area-input">
          <input
            aria-label={`Area ${index + 1}`}
            type="number"
            min="0.0001"
            step="any"
            value={area}
            onChange={(e) =>
              update(
                "acres",
                e.target.value === "" ? "" : toAcres(e.target.value, unit),
              )
            }
          />
          <select
            aria-label={`Area unit ${index + 1}`}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          >
            <option value="acres">acres</option>
            <option value="sqft">sq ft</option>
          </select>
        </div>
      </label>
      <label>
        Irrigation
        <select
          aria-label={`Irrigation ${index + 1}`}
          value={block.irrigation}
          onChange={(e) => update("irrigation", e.target.value)}
        >
          {issue && (
            <option value={block.irrigation} disabled>
              {IRRIGATION[block.irrigation]} (no cost data)
            </option>
          )}
          {priced.map((key) => (
            <option key={key} value={key}>
              {IRRIGATION[key]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Start
        <select
          aria-label={`Start month ${index + 1}`}
          value={block.start_month}
          onChange={(e) => update("start_month", Number(e.target.value))}
        >
          {MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label>
        End
        <select
          aria-label={`End month ${index + 1}`}
          value={block.end_month}
          onChange={(e) => update("end_month", Number(e.target.value))}
        >
          {MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="icon-button remove"
        onClick={onRemove}
        aria-label={`Remove crop ${index + 1}`}
      >
        <Trash2 size={17} />
      </button>
      {issue && (
        <p className="irrigation-issue" role="alert">
          {issue}
        </p>
      )}
    </div>
  );
}
/**
 * Where applied water comes from. Each acre-ft is charged once: the surface share at the
 * district price, the rest at the well pumping cost (optional.surface_water_share).
 */
function WaterSource({ share, onChange }) {
  const kind = waterSourceKind(share);
  const wells = Math.round((1 - share) * 100);
  return (
    <fieldset className="water-source">
      <legend>Water source</legend>
      <div className="segmented">
        {[
          ["surface", "Surface water"],
          ["well", "Well"],
          ["mix", "Mix"],
        ].map(([key, name]) => (
          <button
            key={key}
            type="button"
            aria-pressed={kind === key}
            onClick={() => onChange(waterSourceShare(key, share))}
          >
            {name}
          </button>
        ))}
      </div>
      {kind === "mix" && (
        <label>
          From wells: {wells}% · surface water: {100 - wells}%
          <input
            type="range"
            aria-label="Share of water from wells"
            min="5"
            max="95"
            step="5"
            value={wells}
            onChange={(e) => onChange(1 - Number(e.target.value) / 100)}
          />
        </label>
      )}
      <p className="caption">
        {kind === "surface"
          ? "All applied water is bought from the irrigation district."
          : kind === "well"
            ? "All applied water is pumped from wells (lift, pump efficiency, and EIA electricity)."
            : "Each acre-foot comes from one source: the well share is pumped, the rest is bought."}
      </p>
    </fieldset>
  );
}

export default function FarmForm({
  farm,
  setFarm,
  onRun,
  busy,
  error,
  mock,
  onReset,
  meta,
}) {
  const [query, setQuery] = useState(""),
    [matches, setMatches] = useState([]),
    [searching, setSearching] = useState(false),
    [searchError, setSearchError] = useState("");
  function updateLocation(key, value) {
    setFarm({ ...farm, location: { ...farm.location, [key]: value } });
  }
  function optional(key, value) {
    setFarm({ ...farm, optional: { ...farm.optional, [key]: value } });
  }
  async function search() {
    if (query.trim().length < 2) {
      setSearchError("Enter at least two characters to search.");
      return;
    }
    setSearching(true);
    setSearchError("");
    try {
      const result = await geocode(query.trim(), { mock });
      setMatches(result);
      if (!result.length)
        setSearchError(
          mock
            ? "No demo location found. Try Merced, Fresno, Sacramento, Nairobi, New Delhi, or São Paulo. You can also enter coordinates."
            : "No matches. Try a city name or enter coordinates.",
        );
    } catch (e) {
      setSearchError(e.message);
    } finally {
      setSearching(false);
    }
  }
  return (
    <div className="farm-layout">
      <form
        id="farm-form"
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
        noValidate
      >
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">01 / LOCATION</span>
              <h2>Where do you grow?</h2>
            </div>
            <MapPin size={21} className="muted-icon" />
          </div>
          <p className="subtle">
            Choose your farm's location. You can start with our Merced example.
          </p>
          <label htmlFor="location-search">Search city or ZIP</label>
          <div className="search-row">
            <div className="search-input">
              <Search size={17} />
              <input
                id="location-search"
                value={query}
                placeholder="Try Merced, California"
                onChange={(e) => {
                  setQuery(e.target.value);
                  setMatches([]);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    search();
                  }
                }}
              />
            </div>
            <button
              type="button"
              className="secondary"
              onClick={search}
              disabled={searching}
            >
              {searching ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                "Search"
              )}
            </button>
          </div>
          {searchError && (
            <p className="field-error" role="alert">
              {searchError}
            </p>
          )}
          {matches.length > 0 && (
            <ul className="search-results">
              {matches.map((place, i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => {
                      setFarm({
                        ...farm,
                        location: {
                          lat: place.lat,
                          lon: place.lon,
                          label: place.label,
                        },
                      });
                      setQuery("");
                      setMatches([]);
                    }}
                  >
                    <MapPin size={15} />
                    {place.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="selected-location">
            <span className="location-dot" />
            <div>
              <strong>{farm.location.label || "Unnamed location"}</strong>
              <small>
                {farm.location.lat}, {farm.location.lon}
              </small>
            </div>
            <span className="chip">Selected</span>
          </div>
          <details className="disclosure">
            <summary>Enter coordinates instead</summary>
            <div className="form-grid three">
              <label>
                Location label
                <input
                  value={farm.location.label}
                  onChange={(e) => updateLocation("label", e.target.value)}
                />
              </label>
              <label>
                Latitude
                <input
                  type="number"
                  step="any"
                  value={farm.location.lat}
                  onChange={(e) => updateLocation("lat", e.target.value)}
                />
              </label>
              <label>
                Longitude
                <input
                  type="number"
                  step="any"
                  value={farm.location.lon}
                  onChange={(e) => updateLocation("lon", e.target.value)}
                />
              </label>
            </div>
          </details>
        </section>
        <LandBudgetPanel
          farm={farm}
          setFarm={setFarm}
          eyebrow="02 / LAND AND BUDGET"
        />
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">03 / CROPS</span>
              <h2>What is in the ground?</h2>
            </div>
            <span className="chip">{farm.blocks.length} crop entries</span>
          </div>
          <p className="subtle">
            Add each crop and its growing months. Year-round crops are
            prefilled; you can edit every date.
          </p>
          <div className="crop-editors">
            {farm.blocks.map((block, index) => (
              <BlockEditor
                key={block.id}
                block={block}
                index={index}
                meta={meta}
                onChange={(changed) =>
                  setFarm({
                    ...farm,
                    blocks: farm.blocks.map((b) =>
                      b.id === block.id ? changed : b,
                    ),
                  })
                }
                onRemove={() =>
                  setFarm({
                    ...farm,
                    blocks: farm.blocks.filter((b) => b.id !== block.id),
                  })
                }
              />
            ))}
          </div>
          <button
            type="button"
            className="add-crop"
            onClick={() =>
              setFarm({
                ...farm,
                blocks: [
                  ...farm.blocks,
                  {
                    id: `b${crypto.randomUUID().slice(0, 8)}`,
                    crop: "corn",
                    acres: 10,
                    irrigation: "drip",
                    start_month: 5,
                    end_month: 9,
                  },
                ],
              })
            }
          >
            <Plus size={16} /> Add another crop
          </button>
          <p className="caption">
            Crop area across entries:{" "}
            {number(
              farm.blocks.reduce((s, b) => s + Number(b.acres || 0), 0),
              1,
            )}{" "}
            acres. Successive crops may use the same land.
          </p>
        </section>
        <Timeline blocks={farm.blocks} />
        <LandCheck blocks={farm.blocks} available={farm.available_acres} />
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">04 / HISTORICAL WINDOW</span>
              <h2>Look back before looking ahead.</h2>
            </div>
          </div>
          <PeriodPresets farm={farm} setFarm={setFarm} meta={meta}>
          <div className="form-grid two">
            <label>
              From year
              <input
                type="number"
                min="1984"
                max={new Date().getFullYear() - 1}
                value={farm.years[0]}
                onChange={(e) =>
                  setFarm({ ...farm, years: [e.target.value, farm.years[1]] })
                }
              />
            </label>
            <label>
              Through year
              <input
                type="number"
                min="1984"
                max={new Date().getFullYear() - 1}
                value={farm.years[1]}
                onChange={(e) =>
                  setFarm({ ...farm, years: [farm.years[0], e.target.value] })
                }
              />
            </label>
          </div>
          </PeriodPresets>
          <p className="caption">
            These are historical simulations, not a forecast. Crops crossing
            December count in the year their season ends.
          </p>
          <fieldset className="price-mode">
            <legend>Compare economics using</legend>
            <div className="segmented">
              <button
                type="button"
                aria-pressed={farm.price_mode === "current"}
                onClick={() => setFarm({ ...farm, price_mode: "current" })}
              >
                Today's prices
              </button>
              <button
                type="button"
                aria-pressed={farm.price_mode === "historical"}
                onClick={() => setFarm({ ...farm, price_mode: "historical" })}
              >
                Historical prices
              </button>
            </div>
            <p className="caption">
              {farm.price_mode === "current"
                ? "Use the latest available prices in every year to compare weather scenarios."
                : "Use each historical year’s own prices. Missing data may leave financial results unavailable."}
            </p>
          </fieldset>
        </section>
        <section className="panel optional-panel">
          <details>
            <summary>
              <SlidersHorizontal size={18} />
              <div>
                <strong>Optional farm details</strong>
                <span>Water budget, soil, and water sources</span>
              </div>
              <Plus size={17} />
            </summary>
            <div className="optional-content">
              <p className="caption">
                Leave unknown water amounts blank. A zero budget means no
                irrigation water is available.
              </p>
              <div className="form-grid two">
                <label>
                  Soil texture
                  <select
                    value={farm.optional.soil}
                    onChange={(e) => optional("soil", e.target.value)}
                  >
                    <option value="sand">Sand</option>
                    <option value="loam">Loam (default assumption)</option>
                    <option value="clay">Clay</option>
                  </select>
                </label>
                <label>
                  Water available / year (acre-ft)
                  <input
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Unknown"
                    value={farm.optional.water_available_af ?? ""}
                    onChange={(e) =>
                      optional("water_available_af", e.target.value)
                    }
                  />
                </label>
                <label>
                  Water actually applied / year (acre-ft)
                  <input
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Unknown"
                    value={farm.optional.water_applied_af ?? ""}
                    onChange={(e) =>
                      optional("water_applied_af", e.target.value)
                    }
                  />
                </label>
              </div>
              <WaterSource
                share={Number(farm.optional.surface_water_share)}
                onChange={(v) => optional("surface_water_share", v)}
              />
            </div>
          </details>
        </section>
        {error && (
          <div className="error-box" role="alert">
            {error}
          </div>
        )}
        <div className="run-row">
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={onReset}
          >
            <RotateCcw size={14} /> Reset example
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? (
              <>
                <LoaderCircle size={17} className="spin" />
                Running {mock ? "demo" : "backtest"}...
              </>
            ) : (
              <>
                Run {mock ? "demo backtest" : "backtest"}
                <ArrowUpRight size={18} />
              </>
            )}
          </button>
        </div>
      </form>
      <aside className="setup-aside">
        <span className="eyebrow">A CLEARER PICTURE OF YOUR FARM</span>
        <h2>
          Different years.
          <br />
          Better questions.
        </h2>
        <div className="contour-art" aria-hidden="true">
          <div />
          <div />
          <div />
          <span>YIELD / WATER / POSSIBILITIES</span>
        </div>
        <div className="aside-step">
          <b>01</b>
          <div>
            <strong>Describe your farm</strong>
            <p>Your crops, area, and growing calendar.</p>
          </div>
        </div>
        <div className="aside-step">
          <b>02</b>
          <div>
            <strong>Explore the history</strong>
            <p>See how the same farm might perform across past weather.</p>
          </div>
        </div>
        <div className="aside-step">
          <b>03</b>
          <div>
            <strong>Compare a change</strong>
            <p>Keep your baseline and explore one alternative at a time.</p>
          </div>
        </div>
        <div className="aside-note">
          {mock
            ? "Demo mode uses invented results to test the interface. It does not make real yield predictions."
            : "Results depend on the backend model, crop parameters, and available local evidence."}
        </div>
      </aside>
    </div>
  );
}
