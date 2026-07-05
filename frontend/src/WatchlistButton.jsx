import React, { useState } from "react";
import { addToWatchlist, removeFromWatchlist } from "./api.js";

// Star/heart toggle. Saves to the DB-backed Watchlist table (POST/DELETE
// /api/watchlist/{property_id}), not localStorage, so it's shared across
// devices/sessions per the Phase 3 spec ("watchlist in DB").
export default function WatchlistButton({ propertyId, initialWatchlisted = false, onChange }) {
  const [watchlisted, setWatchlisted] = useState(!!initialWatchlisted);
  const [busy, setBusy] = useState(false);

  async function toggle(e) {
    e.stopPropagation(); // don't also trigger the card/row's onClick (open detail)
    if (busy) return;
    setBusy(true);
    const next = !watchlisted;
    setWatchlisted(next); // optimistic
    try {
      if (next) {
        await addToWatchlist(propertyId);
      } else {
        await removeFromWatchlist(propertyId);
      }
      if (onChange) onChange(next);
    } catch (err) {
      setWatchlisted(!next); // revert on failure
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      className={`watchlist-btn${watchlisted ? " active" : ""}`}
      onClick={toggle}
      disabled={busy}
      title={watchlisted ? "Remove from watchlist" : "Add to watchlist"}
      aria-pressed={watchlisted}
    >
      {watchlisted ? "★" : "☆"}
    </button>
  );
}
