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

export async function getScrapeStatus() {
  const res = await fetch(`${BASE_URL}/api/scrape/status`);
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

export const API_BASE_URL = BASE_URL;
