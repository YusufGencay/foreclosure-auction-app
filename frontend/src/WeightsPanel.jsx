import React, { useEffect, useState } from "react";
import { getWeights, putWeights } from "./api.js";

export default function WeightsPanel() {
  const [weights, setWeights] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    // GET /api/weights returns a plain list directly, not {weights: [...]} -
    // the old code set state to undefined here, which would crash this
    // whole tab the moment it tried to render weights.map(...).
    getWeights().then(setWeights).catch((e) => setError(e.message));
  }, []);

  function handleChange(key, value) {
    setWeights((prev) => prev.map((w) => (w.key === key ? { ...w, weight: value } : w)));
  }

  async function handleSave() {
    setSaving(true);
    try {
      // PUT /api/weights expects {"weights": [{"key": ..., "weight": ...}, ...]} -
      // the old code sent {"weights": {equity_spread: 1.0, ...}} (a flat
      // dict, not a list of {key, weight} objects), which the backend's
      // Pydantic model would reject with a 422 on every save attempt.
      const payload = weights.map((w) => ({ key: w.key, weight: parseFloat(w.weight) }));
      const result = await putWeights(payload);
      setWeights(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="weights-panel">
      <h3>Ranking Score Weights</h3>

      {/* Phase 4 (2026-07-13): the primary dashboard ranking_score is now a
          fixed 85% profit-gap / 15% location formula (see PROJECT_CONTEXT.md
          for the full spec) - it is NOT driven by the per-component sliders
          below anymore. Showing this read-only, per spec ("expose the 85/15
          split read-only... don't leave a stale UI lying to the user") so
          nobody drags a slider expecting it to move the number the
          dashboard actually sorts by. */}
      <div className="fixed-split-panel">
        <div className="fixed-split-row">
          <span className="fixed-split-label">💰 Profit potential</span>
          <div className="fixed-split-bar"><div className="fixed-split-fill" style={{ width: "85%" }} /></div>
          <span className="fixed-split-pct">85%</span>
        </div>
        <div className="fixed-split-row">
          <span className="fixed-split-label">📍 Location (crime / flood / market)</span>
          <div className="fixed-split-bar"><div className="fixed-split-fill" style={{ width: "15%" }} /></div>
          <span className="fixed-split-pct">15%</span>
        </div>
        <p className="fixed-split-note">
          This split is fixed, per the investor's explicit spec (2026-07-13): the score should heavily prioritize
          real profit (estimated value vs. max bid, minus known costs), with location a smaller factor. Lien-priority
          and bankruptcy flags never affect this number - they show as loud red warning badges instead. Click any
          property's score to see the exact numbers behind it.
        </p>
      </div>

      <h3>Legacy composite score weights</h3>
      <p className="fixed-split-note">
        These sliders only affect the older <code>composite_score</code> field (not shown prominently in the UI
        anymore) - they do not change the ranking_score above or the dashboard's sort order.
      </p>
      {error && <div className="error-text">{error}</div>}
      {weights.map((w) => (
        <div key={w.key} className="weight-row">
          <label>
            <span className="weight-key">{w.key}</span>
            <input
              type="range"
              min={-200}
              max={200}
              step={w.key.includes("weight") ? 0.001 : 1}
              value={w.weight}
              onChange={(e) => handleChange(w.key, e.target.value)}
            />
            <input
              type="number"
              step="any"
              value={w.weight}
              onChange={(e) => handleChange(w.key, e.target.value)}
            />
          </label>
          <div className="weight-desc">{w.description}</div>
        </div>
      ))}
      <button onClick={handleSave} disabled={saving}>{saving ? "Saving..." : "Save Weights"}</button>
    </div>
  );
}
