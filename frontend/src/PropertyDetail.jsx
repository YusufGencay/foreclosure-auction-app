import React, { useEffect, useState } from "react";
import WarningBanners from "./WarningBanners.jsx";
import ScoreExplainer from "./ScoreExplainer.jsx";
import WatchlistButton from "./WatchlistButton.jsx";
import NotesPad from "./NotesPad.jsx";
import PreBidChecklist from "./PreBidChecklist.jsx";
import { getProperty, updateProperty, runTitleSearch, enrichProperty, createBidRecord, getBidRecords } from "./api.js";

export default function PropertyDetail({ propertyId, onClose, onUpdated }) {
  const [property, setProperty] = useState(null);
  const [notes, setNotes] = useState("");
  const [rehab, setRehab] = useState("");
  const [titleResult, setTitleResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichNote, setEnrichNote] = useState(null);
  const [showChecklist, setShowChecklist] = useState(false);
  const [bidRecords, setBidRecords] = useState([]);
  const [bidForm, setBidForm] = useState({ bid_amount: "", sale_price: "", winner: "", notes: "" });
  const [bidSaving, setBidSaving] = useState(false);

  function loadBidRecords(id) {
    getBidRecords(id).then(setBidRecords).catch((e) => setError(e.message));
  }

  useEffect(() => {
    if (!propertyId) return;
    getProperty(propertyId)
      .then((p) => {
        setProperty(p);
        setNotes(p.notes || "");
        setRehab(p.rehab_estimate_user_input ?? "");
      })
      .catch((e) => setError(e.message));
    loadBidRecords(propertyId);
  }, [propertyId]);

  async function handleBidFormSubmit(e) {
    e.preventDefault();
    setBidSaving(true);
    try {
      await createBidRecord({
        property_id: propertyId,
        bid_amount: bidForm.bid_amount === "" ? null : parseFloat(bidForm.bid_amount),
        sale_price: bidForm.sale_price === "" ? null : parseFloat(bidForm.sale_price),
        winner: bidForm.winner || null,
        notes: bidForm.notes || null,
      });
      setBidForm({ bid_amount: "", sale_price: "", winner: "", notes: "" });
      loadBidRecords(propertyId);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBidSaving(false);
    }
  }

  if (!propertyId) return null;
  if (error) return <div className="modal-backdrop"><div className="modal">Error: {error} <button onClick={onClose}>Close</button></div></div>;
  if (!property) return <div className="modal-backdrop"><div className="modal">Loading...</div></div>;

  // Prefer the real canonical detail-page URL resolved server-side during
  // /enrich (Phase B.1, 2026-07-13: property.zillow_url/realtor_url/
  // redfin_url, only ever set when the scraper actually confirmed a real
  // matching page - see zillow_scraper.py etc.). Fall back to a generic
  // address-search link (which was always guessed, never guaranteed to
  // land on the right property) only if enrich hasn't run yet.
  const zillowUrl = property.zillow_url || `https://www.zillow.com/homes/${encodeURIComponent(property.address || "")}_rb/`;
  const realtorUrl = property.realtor_url || `https://www.realtor.com/realestateandhomes-search/${encodeURIComponent(property.address || "")}`;
  const redfinUrl = property.redfin_url || null;

  // Phase D.1 (2026-07-13): best-effort pre-filled link to propertyscout.io's
  // public address-search page. propertyscout.io's actual search form is a
  // client-rendered SPA behind app.propertyscout.io with no confirmed
  // public deep-link parameter contract (checked live 2026-07-13 - the
  // marketing site's "Property Owner Search" page has Address/City/State/
  // Zip fields, but they're populated via client JS, not URL query params
  // we could verify), so this pre-fills what their URL structure is known
  // to accept (nothing confirmed) and otherwise just lands the investor on
  // the right search page to re-enter the address manually.
  const propertyScoutUrl = `https://propertyscout.io/property-owner-search/?address=${encodeURIComponent(property.address || "")}`;

  // Phase C.3 (2026-07-13): USFWS Wetlands Mapper link-out, centered on the
  // property's geocoded coordinates when available (populated by the
  // real FEMA/Census lookup during /enrich). No scraping - link-out only,
  // per spec. Falls back to the general mapper tool if coordinates aren't
  // available yet (enrich hasn't run, or the address didn't geocode).
  const wetlandsMapperUrl = "https://www.fws.gov/wetlandsmapper";

  // Phase D.2 (2026-07-13): niche.com school ratings. Live-checked
  // 2026-07-13: niche.com's zip-filtered search results are loaded
  // client-side after page load, not present in the initial server
  // response, so a reliable scrape isn't possible without a full browser
  // render - per spec, falling back to a pre-filled link-out instead of
  // guessing/fabricating school data.
  const zipMatch = (property.address || "").match(/\b(\d{5})\b(?!.*\d{5})/);
  const schoolsZip = zipMatch ? zipMatch[1] : null;
  const nicheSchoolsUrl = schoolsZip
    ? `https://www.niche.com/k12/search/best-schools/?zip=${schoolsZip}`
    : null;

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await updateProperty(property.id, {
        notes,
        rehab_estimate_user_input: rehab === "" ? null : parseFloat(rehab),
      });
      setProperty({ ...property, ...updated });
      if (onUpdated) onUpdated();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleFlag(status) {
    try {
      const updated = await updateProperty(property.id, { flag_status: status });
      setProperty({ ...property, ...updated });
      if (onUpdated) onUpdated();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleTitleSearch() {
    try {
      const result = await runTitleSearch(property.id);
      setTitleResult(result);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleEnrich() {
    setEnriching(true);
    setEnrichNote(null);
    try {
      // Real Zillow/Realtor.com/Redfin scrapes - this can take up to a
      // couple of minutes on a cold cache (each of the 3 sites gets a real
      // 30s-max headless-browser attempt), so this button intentionally
      // blocks with a "Refreshing..." state rather than looking broken.
      const updated = await enrichProperty(property.id);
      setProperty(updated);
      if (updated.enrich_cached) {
        setEnrichNote("Estimates were already refreshed within the last 24h - showing cached values.");
      } else if (updated.enrich_errors && updated.enrich_errors.length > 0) {
        setEnrichNote(`Refreshed with some errors: ${updated.enrich_errors.join("; ")}`);
      } else {
        setEnrichNote("Estimates refreshed.");
      }
      if (onUpdated) onUpdated();
    } catch (e) {
      setError(e.message);
    } finally {
      setEnriching(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2>
          {property.address || "(no address)"} {property.is_demo_data && <span className="sample-tag">DEMO DATA - NOT REAL</span>}
          <WatchlistButton propertyId={property.id} initialWatchlisted={property.is_watchlisted} onChange={onUpdated} />
        </h2>

        <ScoreExplainer property={property} defaultExpanded />

        <div className="action-row">
          <button onClick={() => setShowChecklist(true)}>Pre-Bid Checklist</button>
        </div>
        {showChecklist && (
          <PreBidChecklist propertyId={property.id} onClose={() => setShowChecklist(false)} />
        )}
        {property.auction_status === "canceled" && (
          <div className="warning-banner">
            {property.cancellation_reason
              ? `⚠ Canceled: ${property.cancellation_reason} (per the county's source site).`
              : "⚠ This auction no longer appears in the county's source calendar - it may have been canceled, postponed, or satisfied. Verify before bidding."}
          </div>
        )}

        <WarningBanners property={property} />

        <div className="detail-grid">
          <div><strong>Case #:</strong> {property.case_number}</div>
          <div><strong>County:</strong> {property.county}</div>
          <div><strong>Sale date:</strong> {property.sale_date || "—"}</div>
          <div><strong>Owner:</strong> {property.owner_name || "—"}</div>
          <div><strong>Parcel ID:</strong> {property.parcel_id || "—"}</div>
          <div><strong>Property type:</strong> {property.property_type || "—"}</div>
          <div><strong>Beds/Baths:</strong> {property.beds ?? "—"} / {property.baths ?? "—"}</div>
          <div><strong>Sqft:</strong> {property.sqft ?? "—"}</div>
          <div><strong>Year built:</strong> {property.year_built ?? "—"}</div>
          <div><strong>Final judgment:</strong> {property.final_judgment != null ? `$${property.final_judgment.toLocaleString()}` : "—"}</div>
          <div><strong>Opening bid:</strong> {property.opening_bid != null ? `$${property.opening_bid.toLocaleString()}` : "—"}</div>
          <div><strong>Assessed value:</strong> {property.assessed_value != null ? `$${property.assessed_value.toLocaleString()}` : "—"}</div>
          <div><strong>Market value:</strong> {property.market_value != null ? `$${property.market_value.toLocaleString()}` : "—"}</div>
          <div>
            <strong>Plaintiff:</strong>{" "}
            {property.plaintiff_name ? (
              <>
                {property.plaintiff_name}
                {property.plaintiff_type && (
                  <span> ({property.plaintiff_type}{property.plaintiff_type === "other" ? "" : " (auto-classified from name)"})</span>
                )}
                {property.plaintiff_source && (
                  <span style={{ fontSize: "0.75rem", color: "#666" }}> — {property.plaintiff_source}</span>
                )}
              </>
            ) : (
              <>
                unknown / verify manually
                {property.case_lookup_url && (
                  <>
                    {" "}
                    <a href={property.case_lookup_url} target="_blank" rel="noreferrer">look up case ↗</a>
                  </>
                )}
              </>
            )}
          </div>
          <div><strong>Occupancy:</strong> {property.occupancy_status || "—"}</div>
          <div><strong>Lien priority status:</strong> {property.lien_priority_status || "—"}</div>
          <div><strong>Senior lien survives:</strong> {String(property.senior_lien_survives)}</div>
          <div><strong>Taxes owed:</strong> {property.taxes_owed != null ? `$${property.taxes_owed.toLocaleString()}` : "—"}</div>
          <div><strong>Code liens:</strong> {property.code_liens != null ? `$${property.code_liens.toLocaleString()}` : "—"}</div>
          <div><strong>HOA balance:</strong> {property.hoa_balance != null ? `$${property.hoa_balance.toLocaleString()}` : "—"}</div>
          <div>
            <strong>Flood zone:</strong> {property.flood_zone || "—"}
            {property.flood_zone_source && (
              <span style={{ fontSize: "0.75rem", color: "#666" }}> ({property.flood_zone_source})</span>
            )}
          </div>
          <div><strong>Bankruptcy flag:</strong> {String(property.bankruptcy_flag)}</div>
          <div><strong>Redemption notes:</strong> {property.redemption_notes || "—"}</div>
          <div><strong>Legal description:</strong> {property.legal_description || "—"}</div>
          <div><strong>Last scraped at:</strong> {property.last_scraped_at || "never (no live scrape yet)"}</div>
          <div>
            <strong>Auction status:</strong>{" "}
            {property.auction_status === "canceled" ? (
              <span className="status-canceled">
                canceled{property.cancellation_reason ? `: ${property.cancellation_reason}` : " (reason not shown by county)"}
              </span>
            ) : (
              property.auction_status || "—"
            )}
          </div>
          <div><strong>Source URL:</strong> {property.source_url ? <a href={property.source_url} target="_blank" rel="noreferrer">{property.source_url}</a> : "—"}</div>
        </div>

        <h3>Third-party estimates &amp; market conditions</h3>
        <div className="estimates-grid">
          <div><strong>Zillow estimate:</strong> {property.zillow_estimate != null ? `$${Math.round(property.zillow_estimate).toLocaleString()}` : "unavailable"}</div>
          <div><strong>Realtor.com estimate:</strong> {property.realtor_estimate != null ? `$${Math.round(property.realtor_estimate).toLocaleString()}` : "unavailable"}</div>
          <div><strong>Redfin estimate:</strong> {property.redfin_estimate != null ? `$${Math.round(property.redfin_estimate).toLocaleString()}` : "unavailable"}</div>
          <div>
            <strong>Market conditions:</strong>{" "}
            {property.market_conditions ? (
              <span className={`market-condition-tag ${property.market_conditions}`}>{property.market_conditions.replace("_", " ")}</span>
            ) : "unavailable"}
          </div>
          <div><strong>Zip median sale price:</strong> {property.zip_median_sale_price != null ? `$${Math.round(property.zip_median_sale_price).toLocaleString()}` : "unavailable"}</div>
          <div><strong>Estimates last updated:</strong> {property.estimates_last_updated || "never"}</div>
        </div>
        <div className="action-row">
          <button onClick={handleEnrich} disabled={enriching}>
            {enriching ? "Refreshing estimates (can take ~1-2 min)..." : "Refresh Estimates"}
          </button>
        </div>
        {enrichNote && <div className="title-result">{enrichNote}</div>}
        <p style={{ fontSize: "0.75rem", color: "#666" }}>
          Zillow/Realtor.com/Redfin actively block automated browsers, so these can come back "unavailable" even
          after a refresh - this tool never fabricates a number when a site can't be read. Cached for 24h once fetched.
        </p>

        <div className="link-row">
          <a href={zillowUrl} target="_blank" rel="noreferrer">View on Zillow →</a>
          <a href={realtorUrl} target="_blank" rel="noreferrer">View on Realtor.com →</a>
          {redfinUrl && <a href={redfinUrl} target="_blank" rel="noreferrer">View on Redfin →</a>}
        </div>

        <h3>Location risk</h3>
        <div className="detail-grid">
          <div>
            <strong>Crime grade (crimegrade.org):</strong>{" "}
            {property.crime_grade || "unavailable - click Refresh Estimates to look up"}
            {property.crime_grade_source_url && (
              <> <a href={property.crime_grade_source_url} target="_blank" rel="noreferrer">source →</a></>
            )}
          </div>
          <div>
            <strong>Wetlands (USFWS Wetlands Mapper):</strong>{" "}
            <a href={wetlandsMapperUrl} target="_blank" rel="noreferrer">Open Wetlands Mapper →</a>
            {property.latitude != null && property.longitude != null ? (
              <span style={{ fontSize: "0.75rem", color: "#666" }}>
                {" "}(pan/search to {property.latitude.toFixed(5)}, {property.longitude.toFixed(5)} - the mapper tool's
                URL structure doesn't confirm auto-centering, so this coordinate is provided to enter manually)
              </span>
            ) : (
              <span style={{ fontSize: "0.75rem", color: "#666" }}> (run Refresh Estimates first to geocode this property's coordinates)</span>
            )}
          </div>
          <div>
            <strong>Nearby schools (niche.com):</strong>{" "}
            {nicheSchoolsUrl ? (
              <a href={nicheSchoolsUrl} target="_blank" rel="noreferrer">View schools near this zip →</a>
            ) : "no zip code found in address"}
          </div>
        </div>

        <div className="action-row">
          <button onClick={handleTitleSearch}>Run Title Search (configured provider)</button>
          <a
            className="export-btn"
            href={propertyScoutUrl}
            target="_blank"
            rel="noreferrer"
            style={{ display: "inline-block", textDecoration: "none", textAlign: "center" }}
          >
            Manual Title Search (PropertyScout.io) →
          </a>
          <button onClick={() => handleFlag("saved")} className={property.flag_status === "saved" ? "active" : ""}>Flag / Save</button>
          <button onClick={() => handleFlag("dismissed")} className={property.flag_status === "dismissed" ? "active" : ""}>Dismiss</button>
          <button onClick={() => handleFlag("none")}>Clear flag</button>
        </div>
        {titleResult && (
          <div className="title-result">
            <strong>Title search result:</strong> {titleResult.error ? `Error: ${titleResult.error}` : JSON.stringify(titleResult.liens_found)}
          </div>
        )}

        <h3>Rehab estimate (user input)</h3>
        <input
          type="number"
          value={rehab}
          onChange={(e) => setRehab(e.target.value)}
          placeholder="Enter your rehab estimate ($)"
        />

        <h3>Notes</h3>
        <textarea rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div>
          <button onClick={handleSave} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
        </div>

        <h3>Investor Notes (auto-saves)</h3>
        <NotesPad propertyId={property.id} initialValue={property.investor_notes} />

        <h3>Bid History</h3>
        {bidRecords.length === 0 ? (
          <p style={{ fontSize: "0.85rem", color: "#666" }}>No bid history logged yet.</p>
        ) : (
          <table className="county-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Bid amount</th>
                <th>Sale price</th>
                <th>Winner</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {bidRecords.map((r) => (
                <tr key={r.id}>
                  <td>{r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}</td>
                  <td>{r.bid_amount != null ? `$${Math.round(r.bid_amount).toLocaleString()}` : "—"}</td>
                  <td>{r.sale_price != null ? `$${Math.round(r.sale_price).toLocaleString()}` : "—"}</td>
                  <td>{r.winner || "—"}</td>
                  <td>{r.notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form onSubmit={handleBidFormSubmit} className="bid-record-form">
          <input
            type="number"
            placeholder="Bid amount ($)"
            value={bidForm.bid_amount}
            onChange={(e) => setBidForm({ ...bidForm, bid_amount: e.target.value })}
          />
          <input
            type="number"
            placeholder="Sale price ($)"
            value={bidForm.sale_price}
            onChange={(e) => setBidForm({ ...bidForm, sale_price: e.target.value })}
          />
          <input
            type="text"
            placeholder="Winner (e.g. us, third_party)"
            value={bidForm.winner}
            onChange={(e) => setBidForm({ ...bidForm, winner: e.target.value })}
          />
          <input
            type="text"
            placeholder="Notes"
            value={bidForm.notes}
            onChange={(e) => setBidForm({ ...bidForm, notes: e.target.value })}
          />
          <button type="submit" disabled={bidSaving}>{bidSaving ? "Logging..." : "Log Bid"}</button>
        </form>
      </div>
    </div>
  );
}
