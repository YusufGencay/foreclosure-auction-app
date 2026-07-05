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
      <h3>Score Weight Adjustments</h3>
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
