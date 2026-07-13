import React, { useEffect, useRef, useState } from "react";
import { scrapeAll, getScrapeStatus } from "./api.js";

// Phase 1 (2026-07-13): dashboard-wide "Update All Counties" button. Backend
// POST /api/scrape/all runs synchronously (14 counties, up to 45 lookahead
// days each, rate-limited) and can take several minutes, so this component
// doesn't just await it and spin a generic loader - it also polls
// GET /api/scrape-status every ~10s (which now returns {batch, counties})
// for real progress, and reflects a batch already running (started by the
// 06:00/18:00 scheduler, or another tab) even if this component didn't
// trigger it itself. The backend enforces a single in-process lock shared
// between this endpoint and the scheduled job, returning 409 if a second
// run is attempted - that 409 is treated as "someone else is already
// running it", not an error, and this button just starts reflecting that
// run's progress instead.
const POLL_INTERVAL_MS = 10000;

export default function UpdateAllCountiesButton({ onDone }) {
  const [running, setRunning] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPolling() {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const data = await getScrapeStatus();
        const b = data.batch || {};
        setBatch(b);
        if (!b.running) {
          stopPolling();
          setRunning(false);
          if (onDone) onDone();
        }
      } catch (_) {
        // Transient poll failure - skip this tick, keep the button's
        // running state as-is rather than flipping it off on a fluke.
      }
    }, POLL_INTERVAL_MS);
  }

  // On mount, reflect a batch that may already be running (scheduled job,
  // or another browser tab/user) rather than assuming idle.
  useEffect(() => {
    getScrapeStatus()
      .then((data) => {
        const b = data.batch || {};
        if (b.running) {
          setRunning(true);
          setBatch(b);
          startPolling();
        }
      })
      .catch(() => {});
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleClick() {
    setError(null);
    setRunning(true);
    setBatch({ completed: 0, total: 0, last_county: null, last_count: null });
    startPolling();
    try {
      await scrapeAll();
    } catch (e) {
      // A 409 means a scrape is already running elsewhere (double-click, or
      // the twice-daily scheduler firing at the same moment) - that's not a
      // real error, just keep polling/reflecting that run's progress.
      if (!/409/.test(e.message || "")) {
        setError(e.message);
      }
    } finally {
      try {
        const data = await getScrapeStatus();
        setBatch(data.batch);
      } catch (_) {}
      stopPolling();
      setRunning(false);
      if (onDone) onDone();
    }
  }

  return (
    <div className="update-all-counties">
      <button className="update-all-btn" onClick={handleClick} disabled={running}>
        {running && <span className="spinner" />}
        {running ? "Updating…" : "↻ Update All Counties"}
      </button>
      {running && (
        <div className="update-all-progress">
          <div>
            {batch && batch.total
              ? `${batch.completed} of ${batch.total} counties updated` +
                (batch.last_county
                  ? ` (last: ${batch.last_county} — ${batch.last_count ?? 0} properties)`
                  : "")
              : "Starting…"}
          </div>
          <div className="update-all-hint">
            This can take several minutes — 14 counties, rate-limited, up to 2 at a time.
          </div>
        </div>
      )}
      {error && <div className="error-text">{error}</div>}
    </div>
  );
}
