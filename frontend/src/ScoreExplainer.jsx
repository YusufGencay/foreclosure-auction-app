import React, { useState } from "react";

// Phase 5 (2026-07-13): plain-English, expandable breakdown of the Phase 4
// profit-first ranking_score. Every number shown here comes straight from
// the server-computed `score_explanation` object (scoring.py's
// compute_score_explanation, attached to every property by
// _property_to_dict) - this component does NOT recompute or duplicate the
// formula in JS, it only formats numbers the backend already produced, per
// spec ("Every number shown must be the actual number the formula used").

function money(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.round(Math.abs(n)).toLocaleString()}`;
}

function pct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

function costBasisLabel(source) {
  if (source === "final_judgment") return "final judgment";
  if (source === "opening_bid") return "opening bid";
  return "cost";
}

function valueSourceLabel(sources, usedAssessedFallback) {
  if (usedAssessedFallback) return "county assessed value — no Zillow/Realtor/Redfin estimate yet";
  if (!sources || !sources.length) return "—";
  const names = sources.map((s) => (s === "zillow" ? "Zillow" : s === "realtor" ? "Realtor.com" : s === "redfin" ? "Redfin" : s));
  return `avg of ${names.join(", ")}`;
}

function ProfitLine({ profit, profitWeight }) {
  if (profit.profit_score == null) {
    return (
      <div className="score-explainer-line">
        Profit potential ({Math.round((profitWeight ?? 0.85) * 100)}% of score): not scored — {" "}
        {profit.cost_basis == null
          ? "no final judgment or opening bid on record"
          : "no estimated value available (Zillow/Realtor/Redfin and county assessed value are all missing)"}
      </div>
    );
  }
  const gapClamped = profit.profit_gap_pct != null && (profit.profit_gap_pct < 0 || profit.profit_gap_pct > 1);
  return (
    <div className="score-explainer-line">
      <div>
        <strong>💰 Profit potential ({Math.round((profitWeight ?? 0.85) * 100)}% of score):</strong>
      </div>
      <div className="score-explainer-math">
        Estimated value {money(profit.est_value)} ({valueSourceLabel(profit.value_sources, profit.used_assessed_fallback)})
        {" − "}
        {costBasisLabel(profit.cost_basis_source)} {money(profit.cost_basis)}
        {profit.known_costs ? <>{" − "}known costs {money(profit.known_costs)}</> : null}
        {" = "}
        {money(profit.profit_gap_dollars)} potential upside ({pct(profit.profit_gap_pct)} of value)
        {" → "}
        {Math.round(profit.profit_score)}/100
        {gapClamped ? " (clamped)" : ""}
      </div>
    </div>
  );
}

function LocationLine({ location, locationWeight }) {
  const c = location.components || {};
  const crime = c.crime_grade ? `Crime grade ${c.crime_grade.raw_value} (${c.crime_grade.source})` : "Crime grade: unavailable";
  const flood = c.flood_zone
    ? `Flood zone ${c.flood_zone.raw_value} — ${c.flood_zone.score_0_100 >= 50 ? "minimal risk" : "elevated risk"}`
    : "Flood zone: unavailable";
  const market = c.market_conditions
    ? `Market: ${c.market_conditions.raw_value === "buyer_market" ? "buyer's market" : "seller's market"}`
    : "Market: unavailable";

  return (
    <div className="score-explainer-line">
      <div>
        <strong>📍 Location ({Math.round((locationWeight ?? 0.15) * 100)}% of score{location.location_score == null ? ", not yet applied" : ""}):</strong>
      </div>
      <div className="score-explainer-math">
        {crime} · {flood} · {market}
        {location.location_score != null && <> → {Math.round(location.location_score)}/100</>}
      </div>
      {location.note && <div className="score-explainer-note">{location.note}</div>}
    </div>
  );
}

function WarningsLine({ warnings }) {
  return (
    <div className="score-explainer-line">
      <div>
        <strong>⚠️ Warnings (don't change the score):</strong>
      </div>
      <div className="score-explainer-math">
        {warnings && warnings.length ? (
          <ul className="score-explainer-warnings">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        ) : (
          "none"
        )}
      </div>
    </div>
  );
}

export default function ScoreExplainer({ property, defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const exp = property && property.score_explanation;

  if (!exp) return null;

  const scoreLabel = exp.ranking_score != null ? `Score ${Math.round(exp.ranking_score)} / 100` : "Unscored";

  return (
    <div className="score-explainer">
      <button className="score-explainer-toggle" onClick={() => setExpanded((v) => !v)}>
        {scoreLabel} {expanded ? "▾" : "▸"}
      </button>
      {!expanded && exp.unscored_reason && (
        <div className="score-explainer-note">{exp.unscored_reason}</div>
      )}
      {expanded && (
        <div className="score-explainer-body">
          {exp.unscored_reason && <div className="score-explainer-note">{exp.unscored_reason}</div>}
          <ProfitLine profit={exp.profit} profitWeight={exp.profit_weight} />
          <LocationLine location={exp.location} locationWeight={exp.location_weight} />
          <WarningsLine warnings={exp.warnings} />
          <div className="score-explainer-disclaimer">
            Estimates come from Zillow/Realtor/Redfin — always verify before bidding.
          </div>
        </div>
      )}
    </div>
  );
}
