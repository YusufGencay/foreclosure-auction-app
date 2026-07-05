// Small fetch-based API client. No axios needed.
//
// In dev (vite dev server on :5173) we talk to the backend on :8000.
// In production the frontend is served by FastAPI itself from the same
// origin, so API calls should be relative ("/api/...") rather than
// hardcoded to localhost:8000. Vite exposes import.meta.env.DEV for this.
const BASE_URL = import.meta.env.DEV ? "http://localhost:8000" : "";

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

function qs(params) {
  const usp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") usp.set(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export async function getProperties(params) {
  const res = await fetch(`${BASE_URL}/api/properties${qs(params)}`);
  return handle(res);
}

export async function getProperty(id) {
  const res = await fetch(`${BASE_URL}/api/properties/${id}`);
  return handle(res);
}

export async function updateProperty(id, data) {
  const res = await fetch(`${BASE_URL}/api/properties/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handle(res);
}

export async function scrapeCounty(county) {
  const res = await fetch(`${BASE_URL}/api/scrape/${encodeURIComponent(county)}`, { method: "POST" });
  return handle(res);
}

export async function scrapeAll() {
  const res = await fetch(`${BASE_URL}/api/scrape/all`, { method: "POST" });
  return handle(res);
}

// NOTE: the real endpoint is /api/scrape-status (hyphen), not /api/scrape/status -
// this was previously wrong and silently broke the Counties tab.
export async function getScrapeStatus() {
  const res = await fetch(`${BASE_URL}/api/scrape-status`);
  return handle(res);
}

// Full county config/status (platform, portal_url, verified, etc.) - the
// Counties tab needs this, not just the status endpoint above.
export async function getCounties() {
  const res = await fetch(`${BASE_URL}/api/counties`);
  return handle(res);
}

// Phase 1: on-demand Zillow/Realtor.com/Redfin estimates + market
// conditions for one property. Can take 1-2 minutes on a cold cache since
// it drives real headless-browser scrapes server-side.
export async function enrichProperty(id) {
  const res = await fetch(`${BASE_URL}/api/properties/${id}/enrich`);
  return handle(res);
}

export async function getWeights() {
  const res = await fetch(`${BASE_URL}/api/weights`);
  return handle(res);
}

export async function putWeights(weights) {
  const res = await fetch(`${BASE_URL}/api/weights`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weights }),
  });
  return handle(res);
}

export async function runTitleSearch(propertyId) {
  const res = await fetch(`${BASE_URL}/api/title-search/${propertyId}`, { method: "POST" });
  return handle(res);
}

export function exportUrl(format, params) {
  return `${BASE_URL}/api/export${qs({ ...params, format })}`;
}

// Phase 3: column-selectable CSV export - separate endpoint from the
// original /api/export above (which always exports every column).
export function exportCsvColumnsUrl(columns, params) {
  return `${BASE_URL}/api/export/csv${qs({ ...params, columns: columns && columns.length ? columns.join(",") : undefined })}`;
}

// Phase 3: calendar view - all auctions on a single sale_date.
export async function getPropertiesByDate(dateStr, params) {
  const res = await fetch(`${BASE_URL}/api/properties${qs({ ...params, filter: "by_date", date: dateStr })}`);
  return handle(res);
}

// Phase 3: watchlist
export async function getWatchlist() {
  const res = await fetch(`${BASE_URL}/api/watchlist`);
  return handle(res);
}

export async function addToWatchlist(propertyId) {
  const res = await fetch(`${BASE_URL}/api/watchlist/${propertyId}`, { method: "POST" });
  return handle(res);
}

export async function removeFromWatchlist(propertyId) {
  const res = await fetch(`${BASE_URL}/api/watchlist/${propertyId}`, { method: "DELETE" });
  return handle(res);
}

// Phase 3: investor notes (auto-save on blur), distinct from the general
// `notes` field/updateProperty above.
export async function patchNotes(propertyId, investorNotes) {
  const res = await fetch(`${BASE_URL}/api/properties/${propertyId}/notes`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ investor_notes: investorNotes }),
  });
  return handle(res);
}

// Phase 3: bid history log
export async function createBidRecord(record) {
  const res = await fetch(`${BASE_URL}/api/bid-records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(record),
  });
  return handle(res);
}

export async function getBidRecords(propertyId) {
  const res = await fetch(`${BASE_URL}/api/bid-records${qs({ property_id: propertyId })}`);
  return handle(res);
}

export const API_BASE_URL = BASE_URL;
