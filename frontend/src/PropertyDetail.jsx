import React, { useEffect, useState } from "react";
import WarningBanners from "./WarningBanners.jsx";
import { getProperty, updateProperty, runTitleSearch } from "./api.js";

export default function PropertyDetail({ propertyId, onClose, onUpdated }) {
  const [property, setProperty] = useState(null);
  const [notes, setNotes] = useState("");
  const [rehab, setRehab] = useState("");
  const [titleResult, setTitleResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!propertyId) return;
    getProperty(propertyId)
      .then((p) => {
        setProperty(p);
        setNotes(p.notes || "");
        setRehab(p.rehab_estimate_user_input ?? "");
      })
      .catch((e) => setError(e.message));
  }, [propertyId]);

  if (!propertyId) return null;
  if (error) return <div className="modal-backdrop"><div className="modal">Error: {error} <button onClick={onClose}>Close</button></div></div>;
  if (!property) return <div className="modal-backdrop"><div className="modal">Loading...</div></div>;

  const zillowUrl = `https://www.zillow.com/homes/${encodeURIComponent(property.address || "")}_rb/`;
  const realtorUrl = `https://www.realtor.com/realestateandhomes-search/${encodeURIComponent(property.address || "")}`;

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

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2>{property.address || "(no address)"} {property.is_sample_data && <span className="sample-tag">SAMPLE DATA</span>}</h2>
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
          <div><strong>Plaintiff:</strong> {property.plaintiff_name || "—"} ({property.plaintiff_type || "—"})</div>
          <div><strong>Occupancy:</strong> {property.occupancy_status || "—"}</div>
          <div><strong>Lien priority status:</strong> {property.lien_priority_status || "—"}</div>
          <div><strong>Senior lien survives:</strong> {String(property.senior_lien_survives)}</div>
          <div><strong>Taxes owed:</strong> {property.taxes_owed != null ? `$${property.taxes_owed.toLocaleString()}` : "—"}</div>
          <div><strong>Code liens:</strong> {property.code_liens != null ? `$${property.code_liens.toLocaleString()}` : "—"}</div>
          <div><strong>HOA balance:</strong> {property.hoa_balance != null ? `$${property.hoa_balance.toLocaleString()}` : "—"}</div>
          <div><strong>Flood zone:</strong> {property.flood_zone || "—"}</div>
          <div><strong>Bankruptcy flag:</strong> {String(property.bankruptcy_flag)}</div>
          <div><strong>Redemption notes:</strong> {property.redemption_notes || "—"}</div>
          <div><strong>Legal description:</strong> {property.legal_description || "—"}</div>
          <div><strong>Last scraped at:</strong> {property.last_scraped_at || "never (no live scrape yet)"}</div>
          <div><strong>Source URL:</strong> {property.source_url ? <a href={property.source_url} target="_blank" rel="noreferrer">{property.source_url}</a> : "—"}</div>
        </div>

        <h3>Score breakdown</h3>
        <pre className="score-block">{JSON.stringify(property.score, null, 2)}</pre>

        <div className="link-row">
          <a href={zillowUrl} target="_blank" rel="noreferrer">View on Zillow →</a>
          <a href={realtorUrl} target="_blank" rel="noreferrer">View on Realtor.com →</a>
        </div>

        <div className="action-row">
          <button onClick={handleTitleSearch}>Run Title Search</button>
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
      </div>
    </div>
  );
}
