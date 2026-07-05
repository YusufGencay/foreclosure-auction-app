import React, { useEffect, useState } from "react";
import { getCounties, scrapeCounty, scrapeAll } from "./api.js";

export default function CountyPanel() {
  const [counties, setCounties] = useState([]);
  const [loadingCounty, setLoadingCounty] = useState(null);
  const [error, setError] = useState(null);

  // NOTE: this used to call getScrapeStatus() (GET /api/scrape-status),
  // which only returns {county, last_scraped_at, last_scrape_success,
  // last_scrape_error} - it never had .region/.platform/.confirmed/
  // .portal_url, so most of this table silently rendered blank. GET
  // /api/counties has the full config this panel actually needs.
  async function refresh() {
    try {
      const data = await getCounties();
      setCounties(data || []);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function handleScrape(name) {
    setLoadingCounty(name);
    try {
      await scrapeCounty(name);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingCounty(null);
      refresh();
    }
  }

  async function handleScrapeAll() {
    setLoadingCounty("__all__");
    try {
      await scrapeAll();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingCounty(null);
      refresh();
    }
  }

  return (
    <div className="county-panel">
      <div className="county-panel-header">
        <h3>County Scrape Status</h3>
        <button onClick={handleScrapeAll} disabled={loadingCounty === "__all__"}>
          {loadingCounty === "__all__" ? "Refreshing all..." : "Refresh All"}
        </button>
      </div>
      {error && <div className="error-text">{error}</div>}
      <table className="county-table">
        <thead>
          <tr>
            <th>County</th>
            <th>Platform</th>
            <th>Confirmed</th>
            <th>Last successful scrape</th>
            <th>Status</th>
            <th>Portal</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {counties.map((c) => (
            <tr key={c.name}>
              <td>{c.name} <span className="region-tag">{c.region}</span></td>
              <td>{c.platform}</td>
              <td>{c.verified ? "yes" : "no"}</td>
              <td>
                {c.last_scrape_success ? c.last_scraped_at : "never"}
              </td>
              <td>
                {c.last_scraped_at
                  ? (c.last_scrape_success ? "success" : `failed: ${c.last_scrape_error || ""}`)
                  : "never attempted"}
              </td>
              <td><a href={c.portal_url} target="_blank" rel="noreferrer">portal ↗</a></td>
              <td>
                <button onClick={() => handleScrape(c.name)} disabled={loadingCounty === c.name}>
                  {loadingCounty === c.name ? "..." : "Refresh"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
