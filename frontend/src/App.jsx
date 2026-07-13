import React, { useEffect, useState, useCallback } from "react";
import "./App.css";
import { getProperties, exportUrl, exportCsvColumnsUrl } from "./api.js";
import WarningBanners from "./WarningBanners.jsx";
import WatchlistButton from "./WatchlistButton.jsx";
import PropertyDetail from "./PropertyDetail.jsx";
import CountyPanel from "./CountyPanel.jsx";
import WeightsPanel from "./WeightsPanel.jsx";
import CalendarView from "./CalendarView.jsx";
import PropertyCard from "./PropertyCard.jsx";
import CsvExportPanel from "./CsvExportPanel.jsx";
import UpdateAllCountiesButton from "./UpdateAllCountiesButton.jsx";

const COUNTIES = [
  "Hillsborough", "Pinellas", "Pasco", "Hernando", "Manatee", "Sarasota",
  "Orange", "Osceola", "Seminole", "Polk", "Lake", "Volusia", "Brevard", "Marion",
];
const PLAINTIFF_TYPES = ["bank", "servicer", "HOA-COA", "tax_cert", "private_lender", "other"];
const OCCUPANCY = ["owner_occupied", "vacant", "tenant_occupied", "unknown"];
const FLAG_STATUSES = ["none", "saved", "dismissed"];

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [view, setView] = useState("dense"); // dense | card
  const [filters, setFilters] = useState({
    county: "", plaintiff_type: "", occupancy_status: "", flag_status: "",
    min_equity_spread: "",
  });
  // Ranking drives the whole dashboard (Phase 2) - default to the same
  // sort the backend itself defaults to (ranking_score DESC) rather than
  // an arbitrary "id" that made the highest-ranked deals invisible unless
  // you manually re-sorted.
  const [sortBy, setSortBy] = useState("ranking_score");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [data, setData] = useState({ results: [], total: 0 });
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [cardIndex, setCardIndex] = useState(0);

  const load = useCallback(() => {
    getProperties({ ...filters, sort_by: sortBy, sort_dir: sortDir, page, page_size: pageSize })
      .then(setData)
      .catch((e) => setError(e.message));
  }, [filters, sortBy, sortDir, page, pageSize]);

  useEffect(() => { load(); }, [load]);

  // Numeric "bigger is better" columns should default to descending on
  // first click (best deals/highest rank first), everything else to
  // ascending (e.g. soonest sale date first).
  const DESC_FIRST_COLUMNS = new Set(["ranking_score", "equity_spread"]);

  function handleSort(col) {
    if (sortBy === col) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(col);
      setSortDir(DESC_FIRST_COLUMNS.has(col) ? "desc" : "asc");
    }
  }

  function handleFilterChange(key, value) {
    setPage(1);
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / pageSize));

  return (
    <div className="app">
      <header className="app-header">
        <h1>Florida Foreclosure Auction Analysis &amp; Ranking Tool</h1>
        <UpdateAllCountiesButton onDone={load} />
        <nav>
          <button className={tab === "dashboard" ? "active" : ""} onClick={() => setTab("dashboard")}>Dashboard</button>
          <button className={tab === "calendar" ? "active" : ""} onClick={() => setTab("calendar")}>Calendar</button>
          <button className={tab === "counties" ? "active" : ""} onClick={() => setTab("counties")}>Counties</button>
          <button className={tab === "weights" ? "active" : ""} onClick={() => setTab("weights")}>Score Weights</button>
        </nav>
      </header>

      {tab === "counties" && <CountyPanel />}
      {tab === "weights" && <WeightsPanel />}
      {tab === "calendar" && <CalendarView onSelectProperty={setSelectedId} />}

      {tab === "dashboard" && (
        <>
          <div className="filters-bar">
            <select value={filters.county} onChange={(e) => handleFilterChange("county", e.target.value)}>
              <option value="">All Counties</option>
              {COUNTIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={filters.plaintiff_type} onChange={(e) => handleFilterChange("plaintiff_type", e.target.value)}>
              <option value="">All Plaintiff Types</option>
              {PLAINTIFF_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select value={filters.occupancy_status} onChange={(e) => handleFilterChange("occupancy_status", e.target.value)}>
              <option value="">All Occupancy</option>
              {OCCUPANCY.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <select value={filters.flag_status} onChange={(e) => handleFilterChange("flag_status", e.target.value)}>
              <option value="">All Flag Status</option>
              {FLAG_STATUSES.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <input
              type="number"
              placeholder="Min equity spread ($)"
              value={filters.min_equity_spread}
              onChange={(e) => handleFilterChange("min_equity_spread", e.target.value)}
            />
            <div className="view-toggle">
              <label>
                <input type="checkbox" checked={view === "card"} onChange={() => setView(view === "dense" ? "card" : "dense")} />
                Card view
              </label>
            </div>
            <a className="export-btn" href={exportUrl("xlsx", filters)}>Export XLSX (all columns)</a>
            <CsvExportPanel filters={filters} />
          </div>

          {error && <div className="error-text">{error}</div>}

          {view === "dense" ? (
            <table className="properties-table">
              <thead>
                <tr>
                  <th onClick={() => handleSort("ranking_score")}>Rank {sortBy === "ranking_score" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th onClick={() => handleSort("county")}>County {sortBy === "county" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th onClick={() => handleSort("sale_date")}>Sale Date {sortBy === "sale_date" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th>Address</th>
                  <th onClick={() => handleSort("equity_spread")}>Equity Spread {sortBy === "equity_spread" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th onClick={() => handleSort("plaintiff_type")}>Plaintiff Type {sortBy === "plaintiff_type" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th onClick={() => handleSort("occupancy_status")}>Occupancy {sortBy === "occupancy_status" ? (sortDir === "asc" ? "▲" : "▼") : ""}</th>
                  <th>Auction Status</th>
                  <th>Flags</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((p) => (
                  <tr key={p.id} onClick={() => setSelectedId(p.id)} className={`clickable-row${p.auction_status === "canceled" ? " row-canceled" : ""}`}>
                    <td className="rank-cell">{p.ranking_score != null ? p.ranking_score.toFixed(1) : "—"}</td>
                    <td>{p.county} {p.is_demo_data && <span className="sample-tag-sm">DEMO</span>}</td>
                    <td>{p.sale_date ? new Date(p.sale_date).toLocaleDateString() : "—"}</td>
                    <td>{p.address || "—"}</td>
                    <td>{p.equity_spread != null ? `$${Math.round(p.equity_spread).toLocaleString()}` : "—"}</td>
                    <td>{p.plaintiff_type || "—"}</td>
                    <td>{p.occupancy_status || "—"}</td>
                    <td>
                      {p.auction_status === "canceled" ? (
                        <span className="status-canceled" title={p.cancellation_reason || "Canceled (no reason given by county site)"}>
                          canceled{p.cancellation_reason ? `: ${p.cancellation_reason}` : ""}
                        </span>
                      ) : (
                        p.auction_status || "—"
                      )}
                    </td>
                    <td><WarningBanners property={p} compact /></td>
                    <td><WatchlistButton propertyId={p.id} initialWatchlisted={p.is_watchlisted} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="card-view">
              {data.results.slice(cardIndex, cardIndex + 2).map((p) => (
                <PropertyCard key={p.id} property={p} onClick={() => setSelectedId(p.id)} />
              ))}
              <div className="card-nav">
                <button disabled={cardIndex === 0} onClick={() => setCardIndex(Math.max(0, cardIndex - 2))}>Prev</button>
                <button disabled={cardIndex + 2 >= data.results.length} onClick={() => setCardIndex(cardIndex + 2)}>Next</button>
              </div>
            </div>
          )}

          <div className="pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
            <span>Page {page} of {totalPages} ({data.total} results)</span>
            <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}

      {selectedId && (
        <PropertyDetail propertyId={selectedId} onClose={() => setSelectedId(null)} onUpdated={load} />
      )}
    </div>
  );
}
