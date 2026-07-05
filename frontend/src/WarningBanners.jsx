import React from "react";

// Loud, unmissable warnings for risk factors. Rendered inline in table rows
// (compact) or in the detail view (full).
//
// The backend (scoring.compute_score) already generates these warning
// strings server-side and returns them as property.warnings, with fuller
// context than this component used to reconstruct client-side (e.g. the
// specific reason for a lien-priority flag). The old version also read a
// `property.score` shape that doesn't exist in the real API response
// (fields like equity_spread/warnings are top-level, not nested under
// `score`) for one now-dead condition - harmless since the equivalent
// plaintiff_type check already covered it, but worth cleaning up while
// switching to the backend's warnings array as the single source of truth.
export default function WarningBanners({ property, compact = false }) {
  if (!property) return null;
  const warnings = property.warnings || [];

  if (warnings.length === 0) return null;

  return (
    <div className={compact ? "warning-banner compact" : "warning-banner"}>
      {warnings.map((w, i) => (
        <div key={i} className="warning-line">⚠ {w}</div>
      ))}
    </div>
  );
}
