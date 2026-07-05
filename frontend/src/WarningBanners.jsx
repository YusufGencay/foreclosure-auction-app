import React from "react";

// Loud, unmissable warnings for risk factors. Rendered inline in table rows
// (compact) or in the detail view (full).
export default function WarningBanners({ property, compact = false }) {
  if (!property) return null;
  const score = property.score || {};
  const warnings = [];

  if (property.plaintiff_type === "HOA-COA" || score.junior_lien_warning) {
    warnings.push("JUNIOR LIEN / HOA-COA FORECLOSURE — buyer may take subject to a surviving senior mortgage.");
  }
  if (property.senior_lien_survives === true) {
    warnings.push("SENIOR LIEN SURVIVES — buyer inherits this debt; equity spread may be largely wiped out.");
  }
  if (property.flood_zone) {
    warnings.push(`FLOOD ZONE: ${property.flood_zone} — verify flood insurance requirements/cost.`);
  }
  if (property.bankruptcy_flag) {
    warnings.push("ACTIVE/RECENT BANKRUPTCY FLAG — sale may be stayed or complicated.");
  }

  if (warnings.length === 0) return null;

  return (
    <div className={compact ? "warning-banner compact" : "warning-banner"}>
      {warnings.map((w, i) => (
        <div key={i} className="warning-line">⚠ {w}</div>
      ))}
    </div>
  );
}
