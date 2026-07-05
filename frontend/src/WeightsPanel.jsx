import React, { useEffect, useState } from "react";
import { getWeights, putWeights } from "./api.js";

export default function WeightsPanel() {
  const [weights, setWeights] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getWeights().then((d) => setWeights(d.weights)).catch((e) => setError(e.message));
  }, []);

  function handleChange(key, value) {
    setWeights((prev) => prev.map((w) => (w.key === key ? { ...w, weight: value } : w)));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const payload = {};
      weights.forEach((w) => { payload[w.key] = parseFloat(w.weight); });
      const result = await putWeights(payload);
      setWeights(result.weights);
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
