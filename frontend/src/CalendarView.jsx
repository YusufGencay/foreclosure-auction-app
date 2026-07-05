import React, { useEffect, useMemo, useState, useCallback } from "react";
import { getProperties, getPropertiesByDate } from "./api.js";
import PropertyCard from "./PropertyCard.jsx";

function toDateStr(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

// Month grid calendar. Loads the whole month's auctions in one call (via
// sale_date_from/to on the existing list endpoint) so each day cell can show
// an auction-count dot without one request per day, then clicking a date
// expands that day's auctions using GET /api/properties?filter=by_date&date=
// (the Phase 3-specified endpoint) via PropertyCard.
export default function CalendarView({ onSelectProperty }) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth()); // 0-indexed
  const [monthCounts, setMonthCounts] = useState({}); // dateStr -> count
  const [selectedDate, setSelectedDate] = useState(null);
  const [dayResults, setDayResults] = useState([]);
  const [loadingDay, setLoadingDay] = useState(false);
  const [error, setError] = useState(null);

  const monthStart = useMemo(() => new Date(year, month, 1), [year, month]);
  const monthEnd = useMemo(() => new Date(year, month + 1, 0), [year, month]);

  const loadMonth = useCallback(() => {
    const from = toDateStr(year, month, 1);
    const to = toDateStr(year, month, monthEnd.getDate());
    getProperties({ sale_date_from: from, sale_date_to: to, page_size: 200 })
      .then((data) => {
        const counts = {};
        (data.results || []).forEach((p) => {
          if (!p.sale_date) return;
          const d = p.sale_date.slice(0, 10);
          counts[d] = (counts[d] || 0) + 1;
        });
        setMonthCounts(counts);
      })
      .catch((e) => setError(e.message));
  }, [year, month, monthEnd]);

  useEffect(() => { loadMonth(); }, [loadMonth]);

  function loadDay(dateStr) {
    setSelectedDate(dateStr);
    setLoadingDay(true);
    getPropertiesByDate(dateStr, { page_size: 200 })
      .then((data) => setDayResults(data.results || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoadingDay(false));
  }

  function changeMonth(delta) {
    let m = month + delta;
    let y = year;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    setYear(y);
    setMonth(m);
    setSelectedDate(null);
    setDayResults([]);
  }

  // Build the grid: leading blanks for days-of-week offset, then one cell
  // per day of the month.
  const firstWeekday = monthStart.getDay(); // 0 = Sunday
  const daysInMonth = monthEnd.getDate();
  const cells = [];
  for (let i = 0; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const monthLabel = monthStart.toLocaleString("default", { month: "long", year: "numeric" });
  const todayStr = toDateStr(today.getFullYear(), today.getMonth(), today.getDate());

  return (
    <div className="calendar-view">
      <div className="calendar-header">
        <button onClick={() => changeMonth(-1)}>‹ Prev</button>
        <h3>{monthLabel}</h3>
        <button onClick={() => changeMonth(1)}>Next ›</button>
      </div>

      {error && <div className="error-text">{error}</div>}

      <div className="calendar-grid">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div key={d} className="calendar-dow">{d}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={`blank-${i}`} className="calendar-cell calendar-cell-blank" />;
          const dateStr = toDateStr(year, month, d);
          const count = monthCounts[dateStr] || 0;
          return (
            <div
              key={dateStr}
              className={`calendar-cell${dateStr === selectedDate ? " selected" : ""}${dateStr === todayStr ? " today" : ""}${count > 0 ? " has-auctions" : ""}`}
              onClick={() => count > 0 && loadDay(dateStr)}
            >
              <span className="calendar-day-num">{d}</span>
              {count > 0 && <span className="calendar-count-dot">{count}</span>}
            </div>
          );
        })}
      </div>

      {selectedDate && (
        <div className="calendar-day-expansion">
          <h3>Auctions on {new Date(selectedDate + "T00:00:00").toLocaleDateString()}</h3>
          {loadingDay && <div>Loading...</div>}
          {!loadingDay && dayResults.length === 0 && <div>No auctions found for this date.</div>}
          <div className="card-grid">
            {dayResults.map((p) => (
              <PropertyCard key={p.id} property={p} onClick={() => onSelectProperty(p.id)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
