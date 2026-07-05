import React, { useEffect, useState } from "react";
import { patchNotes } from "./api.js";

// Investor notes textarea - auto-saves to the DB (investor_notes field) on
// blur, per Phase 3 spec. Separate from the general `notes` field/Save
// button already in PropertyDetail (which also carries the scraper's
// NOT_SCRAPED_NOTE default text).
export default function NotesPad({ propertyId, initialValue }) {
  const [value, setValue] = useState(initialValue || "");
  const [status, setStatus] = useState("idle"); // idle | saving | saved | error
  const [lastSavedValue, setLastSavedValue] = useState(initialValue || "");

  useEffect(() => {
    setValue(initialValue || "");
    setLastSavedValue(initialValue || "");
  }, [propertyId, initialValue]);

  async function handleBlur() {
    if (value === lastSavedValue) return; // nothing changed, skip the call
    setStatus("saving");
    try {
      await patchNotes(propertyId, value);
      setLastSavedValue(value);
      setStatus("saved");
      setTimeout(() => setStatus((s) => (s === "saved" ? "idle" : s)), 2000);
    } catch (e) {
      setStatus("error");
    }
  }

  return (
    <div className="notes-pad">
      <textarea
        rows={4}
        value={value}
        placeholder="Investor notes - auto-saves when you click away..."
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleBlur}
      />
      <div className="notes-pad-status">
        {status === "saving" && "Saving..."}
        {status === "saved" && "Saved."}
        {status === "error" && "Failed to save - try again."}
      </div>
    </div>
  );
}
