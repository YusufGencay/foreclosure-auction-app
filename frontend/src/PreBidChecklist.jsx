import React, { useEffect, useState } from "react";

// Modal checklist of pre-bid due-diligence items. Per Phase 3 spec this is
// localStorage-only (not DB-backed) - it's a personal working checklist,
// keyed per-property so each property gets its own saved state.
const CHECKLIST_ITEMS = [
  { key: "title_search", label: "Title search completed" },
  { key: "inspection", label: "Drive-by / physical inspection done" },
  { key: "repair_estimate", label: "Repair/rehab estimate obtained" },
  { key: "occupancy_verified", label: "Occupancy status verified" },
  { key: "liens_reviewed", label: "Liens/judgments reviewed (taxes, HOA, code)" },
  { key: "comps_pulled", label: "Comps pulled for ARV estimate" },
  { key: "funds_ready", label: "Cashier's check / funds ready for bid" },
  { key: "bankruptcy_checked", label: "Bankruptcy filings checked" },
];

function storageKey(propertyId) {
  return `prebid-checklist-${propertyId}`;
}

function loadChecklist(propertyId) {
  try {
    const raw = localStorage.getItem(storageKey(propertyId));
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function saveChecklist(propertyId, state) {
  try {
    localStorage.setItem(storageKey(propertyId), JSON.stringify(state));
  } catch (e) {
    // localStorage unavailable/full - fail silently, nothing critical is lost
  }
}

export default function PreBidChecklist({ propertyId, onClose }) {
  const [checked, setChecked] = useState({});

  useEffect(() => {
    if (propertyId) setChecked(loadChecklist(propertyId));
  }, [propertyId]);

  if (!propertyId) return null;

  function toggle(key) {
    const next = { ...checked, [key]: !checked[key] };
    setChecked(next);
    saveChecklist(propertyId, next);
  }

  const doneCount = CHECKLIST_ITEMS.filter((i) => checked[i.key]).length;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal prebid-modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2>Pre-Bid Checklist</h2>
        <div className="prebid-progress">{doneCount} / {CHECKLIST_ITEMS.length} complete</div>
        <ul className="prebid-list">
          {CHECKLIST_ITEMS.map((item) => (
            <li key={item.key}>
              <label>
                <input
                  type="checkbox"
                  checked={!!checked[item.key]}
                  onChange={() => toggle(item.key)}
                />
                {item.label}
              </label>
            </li>
          ))}
        </ul>
        <p className="prebid-note">Saved locally on this device/browser only.</p>
      </div>
    </div>
  );
}
