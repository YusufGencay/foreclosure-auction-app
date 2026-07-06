import React, { useState } from "react";
import { exportCsvColumnsUrl } from "./api.js";

// Column-selectable CSV export, per Phase 3 spec ("show checkboxes to
// select columns, generate file on download"). Hits GET /api/export/csv,
// distinct from the always-every-column /api/export used by the XLSX link
// next to this component.
const AVAILABLE_COLUMNS = [
  { key: "rank", label: "Rank" },
  { key: "county", label: "County" },
  { key: "address", label: "Address" },
  { key: "sale_date", label: "Sale date" },
  { key: "judgment", label: "Final judgment" },
  { key: "opening_bid", label: "Opening bid" },
  { key: "equity_spread", label: "Equity spread" },
  { key: "market_value", label: "Market value" },
  { key: "taxes_owed", label: "Taxes owed" },
  { key: "hoa_balance", label: "HOA balance" },
  { key: "flag_status", label: "Flag status" },
  { key: "auction_status", label: "Auction status" },
  { key: "cancellation_reason", label: "Cancellation reason" },
];

const DEFAULT_SELECTED = new Set(["rank", "county", "address", "sale_date", "judgment", "opening_bid", "equity_spread"]);

export default function CsvExportPanel({ filters }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(DEFAULT_SELECTED);

  function toggle(key) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  }

  const columns = AVAILABLE_COLUMNS.filter((c) => selected.has(c.key)).map((c) => c.key);
  const href = exportCsvColumnsUrl(columns, filters);

  return (
    <div className="csv-export-panel">
      <button type="button" className="export-btn" onClick={() => setOpen((o) => !o)}>
        Export CSV (choose columns) {open ? "▲" : "▼"}
      </button>
      {open && (
        <div className="csv-export-dropdown">
          {AVAILABLE_COLUMNS.map((c) => (
            <label key={c.key} className="csv-export-checkbox">
              <input type="checkbox" checked={selected.has(c.key)} onChange={() => toggle(c.key)} />
              {c.label}
            </label>
          ))}
          <a
            className="export-btn csv-export-download"
            href={columns.length ? href : undefined}
            aria-disabled={columns.length === 0}
            onClick={(e) => { if (columns.length === 0) e.preventDefault(); }}
          >
            Download CSV ({columns.length} column{columns.length === 1 ? "" : "s"})
          </a>
        </div>
      )}
    </div>
  );
}
