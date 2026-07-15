import React, { useState } from "react";
import WarningBanners from "./WarningBanners.jsx";
import ScoreExplainer from "./ScoreExplainer.jsx";
import WatchlistButton from "./WatchlistButton.jsx";

// Reusable property card - used in the calendar's day expansion, the
// dashboard's card view, and can be reused on any future detail/list page
// per the Phase 3 spec ("PropertyCard is reused in calendar expansion,
// ranked list, and detail page").
//
// Rank color: green 75-100, yellow 50-74, red 0-49 (per spec). Days-to-
// auction badge: red <3 days, yellow 3-7 days, green >7 days.
export function rankColorClass(score) {
  if (score == null) return "rank-unknown";
  if (score >= 75) return "rank-green";
  if (score >= 50) return "rank-yellow";
  return "rank-red";
}

export function daysToAuctionClass(days) {
  if (days == null) return "";
  if (days < 3) return "days-red";
  if (days <= 7) return "days-yellow";
  return "days-green";
}

export default function PropertyCard({ property, onClick, onWatchlistChange }) {
  const [showScore, setShowScore] = useState(false);
  if (!property) return null;
  const rankClass = rankColorClass(property.ranking_score);
  const daysClass = daysToAuctionClass(property.days_to_auction);

  return (
    <div
      className={`property-card-v2${property.auction_status === "canceled" ? " row-canceled" : ""}`}
      onClick={onClick}
    >
      <div className="property-card-v2-top">
        <span
          className={`rank-badge ${rankClass}`}
          onClick={(e) => {
            e.stopPropagation();
            setShowScore((v) => !v);
          }}
          title="Click for a plain-English score breakdown"
        >
          {property.ranking_score != null ? `${Math.round(property.ranking_score)}/100` : "—/100"}
        </span>
        <span className="county-badge">{property.county}</span>
        {property.is_demo_data && <span className="sample-tag-sm">DEMO</span>}
        <WatchlistButton
          propertyId={property.id}
          initialWatchlisted={property.is_watchlisted}
          onChange={onWatchlistChange}
        />
      </div>

      <div className="property-card-v2-address">{property.address || "(no address)"}</div>

      <div className="property-card-v2-figures">
        <div>
          <span className="figure-label">Final judgment</span>
          <span className="figure-value">
            {property.final_judgment != null ? `$${Math.round(property.final_judgment).toLocaleString()}` : "—"}
          </span>
        </div>
        <div>
          <span className="figure-label">Opening bid</span>
          <span className="figure-value">
            {property.opening_bid != null ? `$${Math.round(property.opening_bid).toLocaleString()}` : "—"}
          </span>
        </div>
      </div>

      <div className="property-card-v2-bottom">
        <span>Sale date: {property.sale_date ? new Date(property.sale_date).toLocaleDateString() : "—"}</span>
        {property.days_to_auction != null && (
          <span className={`days-badge ${daysClass}`}>
            {property.days_to_auction < 0
              ? "past"
              : property.days_to_auction === 0
              ? "today"
              : `${property.days_to_auction}d to auction`}
          </span>
        )}
        {property.auction_status === "canceled" && (
          <span className="status-canceled" title={property.cancellation_reason || "Canceled (no reason given by county site)"}>
            canceled{property.cancellation_reason ? `: ${property.cancellation_reason}` : ""}
          </span>
        )}
      </div>

      <WarningBanners property={property} compact />

      {showScore && (
        <div onClick={(e) => e.stopPropagation()}>
          <ScoreExplainer property={property} defaultExpanded />
        </div>
      )}
    </div>
  );
}
